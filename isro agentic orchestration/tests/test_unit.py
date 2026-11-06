"""Unit tests: no network, no LLM, no database."""

from langchain_core.messages import AIMessage, HumanMessage

from orchestrator.agents.common import history_text
from orchestrator.agents.final import numbered_sources
from orchestrator.agents.router import enforce_route, gathered_text, route_from_router
from orchestrator.events import to_jsonable
from orchestrator.graph import build_graph
from orchestrator.mcp_tools import extract_sources, is_empty
from orchestrator.state import SUB_AGENTS, fresh_run_state


# ------------------------------------------------------------------ router guardrails
def test_enforce_route_passes_valid_decision():
    d = {"next_agent": "launch_agent", "task": "next launch", "reason": "live data"}
    assert enforce_route(d, visited=["rag_agent"], hops=1, max_hops=5) == d


def test_enforce_route_blocks_repeat_agent():
    d = enforce_route({"next_agent": "rag_agent", "task": "x", "reason": "r"}, ["rag_agent"], 1, 5)
    assert d["next_agent"] == "final_agent" and "already used" in d["reason"]


def test_enforce_route_hop_limit():
    d = enforce_route({"next_agent": "wikidata_agent", "task": "x", "reason": "r"}, [], 5, 5)
    assert d["next_agent"] == "final_agent" and "hop limit" in d["reason"]


def test_enforce_route_invalid_agent():
    assert enforce_route({"next_agent": "weather_agent", "task": "", "reason": ""}, [], 0, 5)["next_agent"] == "final_agent"


def test_final_allowed_even_at_hop_limit():
    d = {"next_agent": "final_agent", "task": "", "reason": "enough"}
    assert enforce_route(d, list(SUB_AGENTS), 5, 5) == d


def test_conditional_edge_reads_next_agent():
    assert route_from_router({"next_agent": "celestrak_agent"}) == "celestrak_agent"
    assert route_from_router({}) == "final_agent"


# ------------------------------------------------------------------ graph wiring
def test_graph_wiring():
    g = build_graph({a: {} for a in SUB_AGENTS}).get_graph()
    nodes = set(g.nodes)
    assert {"router", "final_agent", *SUB_AGENTS} <= nodes
    edges = {(e.source, e.target) for e in g.edges}
    for a in SUB_AGENTS:
        assert ("router", a) in edges and (a, "router") in edges   # router -> agent -> router
    assert ("router", "final_agent") in edges and ("final_agent", "__end__") in edges
    assert ("__start__", "router") in edges


# ------------------------------------------------------------------ state helpers
def test_fresh_run_state_resets_agent_fields():
    s = fresh_run_state("q")
    assert s["question"] == "q" and s["visited"] == [] and s["hops"] == 0
    assert all(s[a] == "" for a in SUB_AGENTS) and s["final_agent"] == ""


def test_gathered_text_marks_uncalled_agents():
    t = gathered_text({"rag_agent": "some content"})
    assert "some content" in t and "## launch_agent\n(not called yet)" in t


def test_history_excludes_current_question():
    msgs = [HumanMessage("first q"), AIMessage("first a"), HumanMessage("current q")]
    h = history_text(msgs)
    assert "first q" in h and "first a" in h and "current q" not in h


# ------------------------------------------------------------------ tool results / sources
def test_is_empty():
    assert is_empty({"ok": False, "error": "x"})
    assert is_empty({"ok": True, "data": {"satellites": []}})
    assert not is_empty({"ok": True, "data": {"launches": [{"name": "x"}]}})


def test_extract_sources_rag_dedupes_by_section():
    hit = {"title": "GSAT-7", "section": "Key facts", "url": "https://en.wikipedia.org/wiki/GSAT-7", "revision_id": 1}
    res = [{"ok": True, "tool": "search_isro_documents", "args": {}, "data": {"results": [hit, hit]}}]
    src = extract_sources("rag_agent", res)
    assert len(src) == 1 and src[0]["title"] == "GSAT-7 > Key facts"


def test_extract_sources_live_api_and_errors_skipped():
    res = [{"ok": True, "tool": "upcoming_isro_launches", "args": {"limit": 1},
            "data": {"source_url": "https://ll.thespacedevs.com/x", "fetched_at": "t", "launches": []}},
           {"ok": False, "tool": "launch_details", "args": {}, "error": "404"}]
    src = extract_sources("launch_agent", res)
    assert len(src) == 1 and src[0]["url"] == "https://ll.thespacedevs.com/x"


def test_numbered_sources_global_and_deduped():
    s = {"sources": {"rag_agent": [{"title": "A", "url": "u1"}, {"title": "B", "url": "u2"}],
                     "launch_agent": [{"title": "A", "url": "u1"}, {"title": "C", "url": "u3"}]}}
    out = numbered_sources(s)
    assert [x["n"] for x in out] == [1, 2, 3] and [x["title"] for x in out] == ["A", "B", "C"]


def test_usage_reducer_sums_and_breaks_down():
    from orchestrator.state import add_usage, usage_from_calls
    calls = [{"role": "router", "model": "m1", "input_tokens": 100, "output_tokens": 10},
             {"role": "final", "model": "m1", "input_tokens": 50, "output_tokens": 20, "reasoning_tokens": 5}]
    u = usage_from_calls(calls)
    assert (u["llm_calls"], u["input_tokens"], u["output_tokens"], u["reasoning_tokens"]) == (2, 150, 30, 5)
    assert u["by_role"]["router"]["input_tokens"] == 100 and u["by_model"]["m1"]["llm_calls"] == 2
    total = add_usage(u, usage_from_calls(calls[:1]))
    assert total["llm_calls"] == 3 and total["by_role"]["router"]["llm_calls"] == 2


def test_usage_reset_for_new_run():
    from orchestrator.state import add_usage, empty_usage, fresh_run_state, usage_from_calls
    accumulated = usage_from_calls([{"role": "router", "model": "m", "input_tokens": 9, "output_tokens": 1}])
    assert add_usage(accumulated, fresh_run_state("q")["run_usage"]) == empty_usage()
    assert "thread_usage" not in fresh_run_state("q")  # thread totals are never reset


def test_call_record_reads_usage_and_rate_limit_headers():
    from langchain_core.messages import AIMessage as AI
    from orchestrator.llms import call_record
    msg = AI("x", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13,
                                  "output_token_details": {"reasoning": 2}, "input_token_details": {"cache_read": 4}},
             response_metadata={"model_name": "gpt-6-luna", "headers": {"x-ratelimit-remaining-tokens": "999"}})
    r = call_record("router", msg, 1.5)
    assert r == {"role": "router", "model": "gpt-6-luna", "seconds": 1.5, "input_tokens": 10, "output_tokens": 3,
                 "reasoning_tokens": 2, "cached_tokens": 4, "ratelimit_remaining_tokens": 999}


def test_compact_result_keeps_small_and_shortens_large():
    from orchestrator.mcp_tools import RESULT_EVENT_LIMIT, compact_result
    small = {"results": [{"title": "A", "content": "short"}]}
    assert compact_result(small) == small
    big = {"results": [{"title": f"T{i}", "content": "x" * 5000} for i in range(6)]}
    out = compact_result(big)
    assert out["_truncated"] and len(out["results"]) == 6 and out["results"][0]["title"] == "T0"
    import json
    assert len(json.dumps(out)) <= RESULT_EVENT_LIMIT + 50


def test_to_jsonable_messages():
    assert to_jsonable({"messages": [AIMessage("hi")]}) == {"messages": [{"type": "ai", "content": "hi"}]}

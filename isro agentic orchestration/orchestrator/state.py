"""Graph state and the structured-output schemas (TypedDict)."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

SUB_AGENTS = ("rag_agent", "launch_agent", "wikidata_agent", "celestrak_agent")
AgentName = Literal["rag_agent", "launch_agent", "wikidata_agent", "celestrak_agent"]
NextAgent = Literal["rag_agent", "launch_agent", "wikidata_agent", "celestrak_agent", "final_agent"]


class RouterDecision(TypedDict):
    """Decide which agent should gather information next, or hand over to the final agent."""
    next_agent: Annotated[NextAgent, ..., "The next agent to call, or 'final_agent' when enough is known"]
    task: Annotated[str, ..., "Precise instruction for that agent: what to find out (empty for final_agent)"]
    reason: Annotated[str, ..., "One sentence: why this agent / why the information is complete"]


class PlannedToolCall(TypedDict):
    tool: Annotated[str, ..., "Exact tool name from the list"]
    arguments_json: Annotated[str, ..., "Tool arguments as a JSON object string, e.g. {\"limit\": 3}"]


class ToolPlan(TypedDict):
    """Rewrite the request for this data source and plan the tool calls that fetch the data."""
    rewritten_query: Annotated[str, ..., "The request rewritten precisely for this data source"]
    tool_calls: Annotated[list[PlannedToolCall], ..., "1-3 tool calls to run; empty only if no tool fits"]


USAGE_COUNTERS = ("llm_calls", "input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")


class Usage(TypedDict, total=False):
    """Token consumption. Totals plus breakdowns by LLM role and by model."""
    llm_calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    by_role: dict[str, dict[str, int]]
    by_model: dict[str, dict[str, int]]


def empty_usage() -> Usage:
    return {**{k: 0 for k in USAGE_COUNTERS}, "by_role": {}, "by_model": {}}


def _add_counts(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in USAGE_COUNTERS}


def add_usage(left: Usage | None, right: Usage | None) -> Usage:
    """Reducer: sums usage deltas returned by nodes.

    A right-hand value carrying ``"reset": True`` replaces the accumulated value instead
    (used to start a new run's ``run_usage`` from zero).
    """
    if right is None:
        return left or empty_usage()
    if right.get("reset"):
        return {k: v for k, v in right.items() if k != "reset"}
    left = left or empty_usage()
    out: Usage = _add_counts(left, right)
    for group in ("by_role", "by_model"):
        merged = {k: dict(v) for k, v in left.get(group, {}).items()}
        for key, counts in right.get(group, {}).items():
            merged[key] = _add_counts(merged.get(key, {}), counts)
        out[group] = merged
    return out


def usage_from_calls(calls: list[dict]) -> Usage:
    """Build a usage delta from llm_call records (see llms.call_record)."""
    usage = empty_usage()
    for c in calls:
        counts = {"llm_calls": 1, **{k: c.get(k, 0) for k in USAGE_COUNTERS if k != "llm_calls"}}
        usage = add_usage(usage, {**counts, "by_role": {c["role"]: counts}, "by_model": {c["model"]: counts}})
    return usage


class AgentState(TypedDict, total=False):
    # conversation (kept across runs of the same thread by the Postgres checkpointer)
    messages: Annotated[list[AnyMessage], add_messages]
    question: str
    # router's structured block
    next_agent: NextAgent
    task: str
    reason: str
    rag_agent: str
    launch_agent: str
    wikidata_agent: str
    celestrak_agent: str
    final_agent: str
    # bookkeeping
    sources: dict[str, list[dict]]   # per agent
    visited: list[str]
    hops: int
    # token consumption: this question, and the thread's lifetime (kept by the checkpointer)
    run_usage: Annotated[Usage, add_usage]
    thread_usage: Annotated[Usage, add_usage]


def fresh_run_state(question: str) -> dict:
    """Per-question reset. The checkpointer keeps 'messages' (memory) and 'thread_usage' (totals)."""
    return {"question": question, "next_agent": "rag_agent", "task": "", "reason": "",
            **{a: "" for a in SUB_AGENTS}, "final_agent": "", "sources": {}, "visited": [], "hops": 0,
            "run_usage": {**empty_usage(), "reset": True}}


def usage_update(calls: list[dict]) -> dict:
    """State update adding these LLM calls to both run and thread usage."""
    delta = usage_from_calls(calls)
    return {"run_usage": delta, "thread_usage": delta}

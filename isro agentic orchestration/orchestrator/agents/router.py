"""
Router node: an LLM with structured output (RouterDecision) chooses the next agent and its task,
looking at the question, the conversation and the content gathered so far. Guardrails are enforced in
code, not left to the model: no agent twice per question, hop limit, unknown agent -> final.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from .. import prompts
from ..config import get_settings
from ..llms import Timer, call_record, get_llm
from ..state import SUB_AGENTS, AgentState, RouterDecision, usage_update
from .common import emit, history_text, today


def enforce_route(decision: dict, visited: list[str], hops: int, max_hops: int) -> dict:
    """Apply the hard rules to the model's decision (pure function, unit-tested)."""
    nxt, reason = decision.get("next_agent"), decision.get("reason", "")
    if hops >= max_hops and nxt != "final_agent":
        return {**decision, "next_agent": "final_agent", "task": "", "reason": f"hop limit reached ({reason})"}
    if nxt not in (*SUB_AGENTS, "final_agent"):
        return {**decision, "next_agent": "final_agent", "task": "", "reason": f"invalid agent {nxt!r}"}
    if nxt in visited:
        return {**decision, "next_agent": "final_agent", "task": "",
                "reason": f"{nxt} already used for this question ({reason})"}
    return decision


def gathered_text(state: dict) -> str:
    parts = []
    for a in SUB_AGENTS:
        c = state.get(a, "")
        parts.append(f"## {a}\n{c if c else '(not called yet)'}")
    return "\n\n".join(parts)


async def router(state: AgentState) -> dict:
    s = get_settings()
    visited, hops = state.get("visited", []), state.get("hops", 0)
    system = prompts.ROUTER.format(today=today(), capabilities="\n".join(
        f"- {a}: {d}" for a, d in prompts.AGENT_CAPABILITIES.items()))
    human = prompts.ROUTER_INPUT.format(history=history_text(state.get("messages", [])),
                                        question=state.get("question", ""), visited=visited or "none",
                                        hops=hops, max_hops=s.max_hops, gathered=gathered_text(state))
    llm = get_llm("router").with_structured_output(RouterDecision, method="json_schema", include_raw=True)
    with Timer() as t:
        out = await llm.ainvoke([SystemMessage(system), HumanMessage(human)])
    raw_decision = out["parsed"] or {"next_agent": "final_agent", "task": "", "reason": "router produced no decision"}
    decision = enforce_route(raw_decision, visited, hops, s.max_hops)
    record = call_record("router", out["raw"], t.seconds)
    emit("llm_call", "router", **record)

    # The router's structured block, as the frontend shows it: decision + every agent's content so far.
    emit("router_decision", "router",
         structured={"next_agent": decision["next_agent"], "task": decision["task"], "reason": decision["reason"],
                     **{a: state.get(a, "") for a in SUB_AGENTS}, "final_agent": state.get("final_agent", "")},
         overridden=decision != raw_decision, model_choice=raw_decision["next_agent"], seconds=t.seconds)

    update = {"next_agent": decision["next_agent"], "task": decision["task"], "reason": decision["reason"],
              **usage_update([record])}
    if decision["next_agent"] != "final_agent":
        update["hops"] = hops + 1
    return update


def route_from_router(state: AgentState) -> str:
    """Conditional edge: the router's next_agent field picks the next node."""
    return state.get("next_agent") or "final_agent"

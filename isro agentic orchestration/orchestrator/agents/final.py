"""Final agent: one LLM writes the user-facing answer (free text, streamed) from all gathered content."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .. import prompts
from ..llms import Timer, call_record, get_llm
from ..state import SUB_AGENTS, AgentState, usage_update
from .common import emit, history_text, today


def numbered_sources(state: dict) -> list[dict]:
    """All agents' sources, numbered globally [1], [2], ... (deduplicated by title + url)."""
    out, seen = [], set()
    for a in SUB_AGENTS:
        for src in state.get("sources", {}).get(a, []):
            key = (src.get("title"), src.get("url"))
            if key not in seen:
                seen.add(key)
                out.append({"n": len(out) + 1, "agent": a, **src})
    return out


async def final_agent(state: AgentState) -> dict:
    sources = numbered_sources(state)
    src_text = "\n".join(f"[{s['n']}] ({s['agent']}) {s['title']} - {s.get('url') or ''}" for s in sources) or "(none)"
    gathered = "\n\n".join(f"## {a}\n{state.get(a) or '(not called)'}" for a in SUB_AGENTS)
    human = prompts.FINAL_INPUT.format(history=history_text(state.get("messages", [])),
                                       question=state.get("question", ""), gathered=gathered, sources=src_text)
    emit("agent_started", "final_agent", task="write the final answer")
    with Timer() as t:  # tokens are streamed to the client via LangGraph's "messages" stream mode
        msg = await get_llm("final").ainvoke([SystemMessage(prompts.FINAL.format(today=today())), HumanMessage(human)])
    answer = msg.content if isinstance(msg.content, str) else str(msg.content)
    record = call_record("final", msg, t.seconds)
    emit("llm_call", "final_agent", **record)
    emit("final_answer", "final_agent", answer=answer, sources=sources)
    return {"final_agent": answer, "messages": [AIMessage(answer)], **usage_update([record])}

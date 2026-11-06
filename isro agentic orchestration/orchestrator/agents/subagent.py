"""
Sub-agent node factory (rag / launch / wikidata / celestrak). Each node runs:

  1. rewriter LLM   - rewrites the router's task for this data source and plans MCP tool calls
                      (structured output: ToolPlan)
  2. MCP tool calls - executed in code (only this agent's server's tools); one retry with feedback if
                      everything failed or came back empty
  3. generator LLM  - writes the content from the rewritten request + tool results, with source tags

and returns ``{"<agent>": content, "sources": ..., "visited": ..., "run_usage"/"thread_usage": ...}``
to the router. Every LLM call is emitted as an ``llm_call`` event and added to the usage counters.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from .. import prompts
from ..config import get_settings
from ..llms import Timer, call_record, get_llm
from ..mcp_tools import (SOURCE_NAMES, compact_result, describe_tools, extract_sources, is_empty, results_for_prompt,
                         run_tool)
from ..state import AgentState, ToolPlan, usage_update
from .common import emit, today

ROLE_PREFIX = {"rag_agent": "rag", "launch_agent": "launch", "wikidata_agent": "wikidata",
               "celestrak_agent": "celestrak"}


async def _plan(agent: str, tools: dict, question: str, task: str, retry_note: str = "") -> tuple[ToolPlan, dict]:
    """Rewriter LLM: returns the tool plan and the llm_call record."""
    role = f"{ROLE_PREFIX[agent]}_rewriter"
    llm = get_llm(role).with_structured_output(ToolPlan, method="json_schema", include_raw=True)
    system = prompts.REWRITER.format(today=today(), agent=agent, capability=prompts.AGENT_CAPABILITIES[agent],
                                     tools=describe_tools(tools))
    human = prompts.REWRITER_INPUT.format(question=question, task=task or question, retry_note=retry_note)
    with Timer() as t:
        out = await llm.ainvoke([SystemMessage(system), HumanMessage(human)])
    plan = out["parsed"] or {"rewritten_query": task or question, "tool_calls": []}
    record = call_record(role, out["raw"], t.seconds)
    emit("llm_call", agent, **record)
    return plan, record


async def _execute(agent: str, tools: dict, plan: ToolPlan) -> list[dict]:
    """Run the planned MCP calls in parallel; never raises."""
    calls = plan.get("tool_calls", [])[:3]
    for c in calls:
        emit("tool_called", agent, tool=c["tool"], arguments=c["arguments_json"])
    results = await asyncio.gather(*(run_tool(tools, c["tool"], c["arguments_json"]) for c in calls))
    for r in results:
        emit("tool_result", agent, tool=r["tool"], arguments=r["args"], ok=r["ok"], empty=is_empty(r),
             duration_ms=r.get("duration_ms"), error=None if r["ok"] else r["error"][:300],
             result=compact_result(r["data"]) if r["ok"] else None)
    return list(results)


def make_subagent(agent: str, tools: dict):
    """Create the LangGraph node for one sub-agent bound to its own MCP tools."""
    source_name = SOURCE_NAMES[agent]
    generator_role = f"{ROLE_PREFIX[agent]}_generator"

    async def node(state: AgentState) -> dict:
        question, task = state.get("question", ""), state.get("task", "")
        llm_calls: list[dict] = []
        emit("agent_started", agent, task=task)

        # 1. rewrite + plan
        plan, rec = await _plan(agent, tools, question, task)
        llm_calls.append(rec)
        emit("query_rewritten", agent, rewritten_query=plan["rewritten_query"], tool_calls=plan["tool_calls"])

        # 2. tools (+ one retry with feedback)
        results = await _execute(agent, tools, plan)
        if not results or all(is_empty(r) for r in results):
            feedback = "; ".join(f"{r['tool']}({r['args']}): {'error ' + r['error'] if not r['ok'] else 'no results'}"
                                 for r in results) or "no tool was called"
            plan, rec = await _plan(agent, tools, question, task,
                                    retry_note=f"Your previous plan returned nothing useful ({feedback}). "
                                               "Try different tools or simpler search terms.")
            llm_calls.append(rec)
            emit("query_rewritten", agent, rewritten_query=plan["rewritten_query"], tool_calls=plan["tool_calls"],
                 retry=True)
            results += await _execute(agent, tools, plan)

        sources = extract_sources(agent, results)
        tags = "\n".join(f"[S{i}] {s['title']} - {s.get('url') or ''}" for i, s in enumerate(sources, 1)) or "(none)"

        # 3. generate content from the collected data
        human = prompts.GENERATOR_INPUT.format(
            question=question, task=task or question, rewritten_query=plan["rewritten_query"],
            source_name=source_name,
            tool_results=results_for_prompt(results, get_settings().max_tool_result_chars), source_tags=tags)
        with Timer() as t:
            msg = await get_llm(generator_role).ainvoke(
                [SystemMessage(prompts.GENERATOR.format(agent=agent, today=today())), HumanMessage(human)])
        rec = call_record(generator_role, msg, t.seconds)
        llm_calls.append(rec)
        emit("llm_call", agent, **rec)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        emit("agent_content", agent, content=content, sources=sources)

        return {agent: content,
                "sources": {**state.get("sources", {}), agent: sources},
                "visited": [*state.get("visited", []), agent],
                **usage_update(llm_calls)}

    node.__name__ = agent
    return node

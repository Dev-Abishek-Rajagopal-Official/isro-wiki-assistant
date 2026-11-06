"""
Load the isromcp MCP tools, grouped per sub-agent (each agent only ever sees its own server's tools),
and execute planned tool calls.

All MCP servers are reached over streamable HTTP (start them with isromcp/run_http_servers.py).
On Windows the async Postgres driver needs the selector event loop, which cannot spawn stdio
subprocesses; HTTP also avoids one server subprocess per request under FastAPI.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

from .config import get_settings

# sub-agent -> MCP server name (as in isromcp/mcp_config.py)
AGENT_SERVER = {
    "rag_agent": "isro_knowledge_base",
    "launch_agent": "launch_library",
    "wikidata_agent": "wikidata",
    "celestrak_agent": "celestrak",
}
SOURCE_NAMES = {
    "rag_agent": "ISRO knowledge base (Wikipedia)",
    "launch_agent": "Launch Library 2",
    "wikidata_agent": "Wikidata",
    "celestrak_agent": "CelesTrak",
}


def _connections() -> dict:
    s = get_settings()
    sys.path.insert(0, str(s.isromcp_dir))
    from mcp_config import connections  # isromcp's single source of truth for servers/ports

    return connections(s.mcp_transport, only=list(AGENT_SERVER.values()))


async def load_agent_tools() -> dict[str, dict]:
    """{agent: {tool_name: tool}}; fails fast with a clear message if a server is not running."""
    client = MultiServerMCPClient(_connections())
    out: dict[str, dict] = {}
    for agent, server in AGENT_SERVER.items():
        try:
            tools = await client.get_tools(server_name=server)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"MCP server '{server}' not reachable ({type(e).__name__}). Start the servers: "
                               f"cd isromcp && uv run python run_http_servers.py") from e
        out[agent] = {t.name: t for t in tools}
    return out


def describe_tools(tools: dict) -> str:
    parts = []
    for t in tools.values():
        schema = t.args_schema if isinstance(t.args_schema, dict) else t.args
        props = schema.get("properties", schema) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        args = {k: {kk: vv for kk, vv in v.items() if kk in ("type", "description", "default", "enum", "anyOf")}
                for k, v in props.items()}
        parts.append(f"- {t.name}: {t.description.strip()}\n  arguments: {json.dumps(args)}\n  required: {required}")
    return "\n".join(parts)


def _content_text(result) -> str:
    if isinstance(result, tuple):  # (content, artifact)
        result = result[0]
    if isinstance(result, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


RESULT_EVENT_LIMIT = 12_000  # max characters of a tool result stored in the tool_result event


def compact_result(data, limit: int = RESULT_EVENT_LIMIT):
    """Tool result for the event log / UI: unchanged if small; otherwise long text fields are shortened
    (e.g. RAG chunk contents) and, if still too big, a truncated JSON preview is returned."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return data

    def shorten(v, n):
        if isinstance(v, str) and len(v) > n:
            return v[:n] + "…"
        if isinstance(v, list):
            return [shorten(x, n) for x in v]
        if isinstance(v, dict):
            return {k: shorten(x, n) for k, x in v.items()}
        return v

    for n in (1500, 600, 200):
        smaller = shorten(data, n)
        if len(json.dumps(smaller, ensure_ascii=False, default=str)) <= limit:
            return {**smaller, "_truncated": True} if isinstance(smaller, dict) else smaller
    return {"_truncated": True, "preview": text[:limit]}


async def run_tool(tools: dict, tool: str, arguments_json: str) -> dict:
    """Execute one planned call (timed). Never raises: errors come back as {'ok': False, 'error': ...}."""
    t0 = time.perf_counter()
    result = await _run_tool(tools, tool, arguments_json)
    result["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return result


async def _run_tool(tools: dict, tool: str, arguments_json: str) -> dict:
    if tool not in tools:
        return {"tool": tool, "args": arguments_json, "ok": False, "error": f"unknown tool {tool!r}"}
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError as e:
        return {"tool": tool, "args": arguments_json, "ok": False, "error": f"bad arguments: {e}"}
    try:
        text = _content_text(await asyncio.wait_for(tools[tool].ainvoke(args), timeout=90))
    except Exception as e:  # noqa: BLE001
        return {"tool": tool, "args": args, "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    try:
        data = json.loads(text)
    except ValueError:  # MCP tool errors arrive as plain text
        return {"tool": tool, "args": args, "ok": False, "error": text[:500]}
    return {"tool": tool, "args": args, "ok": True, "data": data}


def is_empty(result: dict) -> bool:
    if not result["ok"]:
        return True
    d = result["data"]
    for key in ("results", "launches", "missions", "satellites", "matches", "facts"):
        if key in d:
            return not d[key]
    return False


def extract_sources(agent: str, results: list[dict]) -> list[dict]:
    """Citable sources from tool results (deduplicated)."""
    seen, out = set(), []

    def add(title, url, **extra):
        key = (title, url)
        if title and key not in seen:
            seen.add(key)
            out.append({"title": title, "url": url, **extra})

    for r in results:
        if not r["ok"]:
            continue
        d = r["data"]
        if agent == "rag_agent":
            for h in d.get("results", []):
                add(f"{h['title']} > {h['section']}", h["url"], source="Wikipedia (CC BY-SA 4.0)",
                    revision_id=h.get("revision_id"))
            if "content" in d and "title" in d:  # get_section_context
                add(f"{d['title']} > {d.get('section', '')}", d.get("url"), source="Wikipedia (CC BY-SA 4.0)")
        elif agent == "wikidata_agent" and d.get("qid"):
            add(f"Wikidata: {d.get('label') or d['qid']}", d.get("source_url"), fetched_at=d.get("fetched_at"))
        else:
            add(f"{SOURCE_NAMES[agent]}: {r['tool']}({json.dumps(r['args'], ensure_ascii=False)})",
                d.get("source_url"), fetched_at=d.get("fetched_at"))
    return out


def results_for_prompt(results: list[dict], limit_chars: int) -> str:
    blocks = []
    for i, r in enumerate(results, 1):
        body = json.dumps(r["data"], ensure_ascii=False) if r["ok"] else f"ERROR: {r['error']}"
        blocks.append(f"[call {i}] {r['tool']}({json.dumps(r['args'], ensure_ascii=False)}):\n{body}")
    text = "\n\n".join(blocks)
    return text if len(text) <= limit_chars else text[:limit_chars] + "\n...[truncated]"

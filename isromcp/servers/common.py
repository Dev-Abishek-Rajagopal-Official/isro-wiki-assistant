"""
Shared helpers for the ISRO MCP servers.

fetch_json(url, ttl)  - GET with polite User-Agent, timeout, retries on 5xx/timeouts, and an on-disk
                        SQLite cache. If the API fails or rate-limits (429) and an older cached copy
                        exists, that copy is returned with stale=True instead of an error.
run_server(mcp)       - CLI: stdio (default, for MCP adapters) or streamable HTTP (--http --port N).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / ".cache" / "http_cache.sqlite"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
# Wikimedia (Wikidata) rejects requests whose User-Agent has no contact URL/email (HTTP 403).
CONTACT = os.getenv("MCP_CONTACT", "").strip()
USER_AGENT = f"isro-agent-mcp/0.1 ({CONTACT}; ISRO RAG assignment)" if CONTACT else \
    "isro-agent-mcp/0.1 (ISRO RAG assignment)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    global _db
    if _db is None:
        CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(CACHE_DB, check_same_thread=False)
        _db.execute("CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, body TEXT, fetched REAL)")
    return _db


def _cache_get(url: str) -> tuple[Any, float] | None:
    with _lock:
        row = _conn().execute("SELECT body, fetched FROM cache WHERE url = ?", (url,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def _cache_put(url: str, body: Any) -> None:
    with _lock:
        _conn().execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (url, json.dumps(body), time.time()))
        _conn().commit()


async def fetch_json(url: str, *, params: dict | None = None, ttl: float = 3600,
                     headers: dict | None = None, source: str = "API") -> dict:
    """Returns {"data": <json>, "cached": bool, "stale": bool, "fetched_at": iso}."""
    full = str(httpx.URL(url, params={k: v for k, v in (params or {}).items() if v is not None}))
    cached = _cache_get(full)
    if cached and time.time() - cached[1] < ttl:
        return {"data": cached[0], "cached": True, "stale": False, "fetched_at": _iso(cached[1])}

    last_error = ""
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=TIMEOUT,
                                 follow_redirects=True) as client:
        for attempt in range(3):
            try:
                r = await client.get(full)
                if r.status_code == 200:
                    try:
                        body = r.json()
                    except ValueError:  # e.g. CelesTrak answers bad queries with plain text
                        raise ToolError(f"{source}: {r.text.strip()[:200] or 'empty response'}") from None
                    _cache_put(full, body)
                    return {"data": body, "cached": False, "stale": False, "fetched_at": _iso(time.time())}
                if r.status_code == 429:
                    last_error = f"{source} rate limit reached (HTTP 429)"
                    break  # retrying immediately only burns more quota
                if r.status_code == 404:
                    raise ToolError(f"{source}: not found (404)")
                if r.status_code == 403 and not CONTACT:
                    last_error = (f"{source} refused the request (HTTP 403): set MCP_CONTACT (a URL or email) "
                                  f"in isromcp/.env - Wikimedia requires contact info in the User-Agent")
                    break
                last_error = f"{source} returned HTTP {r.status_code}"
                if r.status_code < 500:
                    break
            except httpx.HTTPError as e:
                last_error = f"{source} request failed: {type(e).__name__}"
            await asyncio.sleep(1.5 * 2 ** attempt)

    if cached:  # serve the last good answer rather than nothing
        return {"data": cached[0], "cached": True, "stale": True, "fetched_at": _iso(cached[1]),
                "warning": f"{last_error}; returning cached data from {_iso(cached[1])}"}
    raise ToolError(last_error or f"{source} request failed")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def meta(resp: dict, source: str, source_url: str) -> dict:
    """Provenance block every tool returns, so the agent can cite where data came from."""
    out = {"source": source, "source_url": source_url, "fetched_at": resp["fetched_at"],
           "from_cache": resp["cached"]}
    if resp.get("stale"):
        out["warning"] = resp["warning"]
    return out


def run_server(mcp, default_port: int) -> None:
    ap = argparse.ArgumentParser(description=f"Run the {mcp.name} MCP server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=default_port)
    args = ap.parse_args()
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port, show_banner=False)
    else:
        mcp.run(transport="stdio", show_banner=False)

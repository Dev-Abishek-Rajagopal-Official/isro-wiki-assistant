"""Health: database, Redis, agent, MCP servers, Qdrant, LLM / Speech configuration (cached 10 s)."""

from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, Response
from orchestrator.config import get_settings as agent_settings
from sqlalchemy import text

router = APIRouter(tags=["health"])

MCP_PORTS = {"isro_knowledge_base": 8101, "launch_library": 8102, "wikidata": 8103, "celestrak": 8104}


async def _tcp(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
        writer.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def _checks(request: Request) -> dict:
    s = request.app.state
    out: dict = {}
    try:
        async with s.db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        out["database"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        out["database"] = {"ok": False, "error": type(e).__name__}
    try:
        out["redis"] = {"ok": bool(await s.redis.ping())}
    except Exception as e:  # noqa: BLE001
        out["redis"] = {"ok": False, "error": type(e).__name__}
    out["agent"] = {"ok": s.agent.ready, **({"error": s.agent.error} if s.agent.error else {})}
    mcp_host = os.getenv("MCP_HOST", "127.0.0.1")  # 'mcp' under docker compose
    mcp = {name: await _tcp(mcp_host, port) for name, port in MCP_PORTS.items()}
    out["mcp_servers"] = {"ok": all(mcp.values()), **mcp}
    qdrant = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{qdrant.rstrip('/')}/readyz")
        out["qdrant"] = {"ok": r.status_code == 200}
    except httpx.HTTPError:
        host = urlparse(qdrant)
        out["qdrant"] = {"ok": await _tcp(host.hostname or "localhost", host.port or 6333)}
    a = agent_settings()
    out["llm"] = {"ok": bool(a.llm_base_url and a.llm_api_key), "model": a.llm_model}
    out["speech"] = {"ok": bool(a.speech_endpoint and a.speech_key)}
    return out


@router.get("/health/live")
async def live() -> dict:
    """Liveness only (the process answers HTTP) - used by container health checks."""
    return {"status": "ok"}


@router.get("/health")
async def health(request: Request, response: Response) -> dict:
    """Overall status is 'ok' only if every dependency is reachable (HTTP 503 otherwise)."""
    cache = request.app.state.cache
    checks = await cache.get("health")
    if checks is None:
        checks = await _checks(request)
        await cache.set("health", checks, ttl=10)
    ok = all(c.get("ok") for c in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "checked_at": int(time.time()), "checks": checks}

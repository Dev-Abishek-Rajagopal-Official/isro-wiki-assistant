"""
Admin analytics (all users). Only accounts listed in ADMIN_EMAILS can call these; everyone else gets 404.
Every response is cached in Redis for ADMIN_CACHE_TTL_S (default 60 s).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser, CacheDep, SessionDep
from app.core.config import get_settings
from app.services import admin as svc

router = APIRouter(prefix="/admin", tags=["admin"])

FROM = Query(None, alias="from", description="ISO datetime, inclusive")
TO = Query(None, alias="to", description="ISO datetime, exclusive")


async def _cached(cache, key: str, producer):
    return await cache.get_or_set(f"admin:{key}", get_settings().admin_cache_ttl_s, producer)


@router.get("/overview")
async def overview(_: AdminUser, session: SessionDep, cache: CacheDep, period_from: datetime | None = FROM,
                   period_to: datetime | None = TO) -> dict:
    """Users (total / active), conversations, threads, requests, success/error rate, latency, tokens."""
    return await _cached(cache, f"overview:{period_from}:{period_to}",
                         lambda: svc.overview(session, period_from, period_to))


@router.get("/timeseries")
async def timeseries(_: AdminUser, session: SessionDep, cache: CacheDep,
                     bucket: Literal["hour", "day", "week"] = "day", period_from: datetime | None = FROM,
                     period_to: datetime | None = TO) -> list[dict]:
    """Requests, errors, latency and tokens per time bucket (for charts)."""
    return await _cached(cache, f"ts:{bucket}:{period_from}:{period_to}",
                         lambda: svc.timeseries(session, bucket, period_from, period_to))


@router.get("/agents")
async def agents(_: AdminUser, session: SessionDep, cache: CacheDep, period_from: datetime | None = FROM,
                 period_to: datetime | None = TO) -> dict:
    """Agent usage, router routes, average agents per run, LLM calls/tokens per agent node."""
    return await _cached(cache, f"agents:{period_from}:{period_to}",
                         lambda: svc.agents(session, period_from, period_to))


@router.get("/tools")
async def tools(_: AdminUser, session: SessionDep, cache: CacheDep, period_from: datetime | None = FROM,
                period_to: datetime | None = TO) -> list[dict]:
    """MCP tool calls: count, failures, empty results, average duration."""
    return await _cached(cache, f"tools:{period_from}:{period_to}",
                         lambda: svc.tools(session, period_from, period_to))


@router.get("/models")
async def models(_: AdminUser, session: SessionDep, cache: CacheDep, period_from: datetime | None = FROM,
                 period_to: datetime | None = TO) -> dict:
    """LLM calls and tokens by model and by LLM role."""
    return await _cached(cache, f"models:{period_from}:{period_to}",
                         lambda: svc.models(session, period_from, period_to))


@router.get("/users")
async def users(_: AdminUser, session: SessionDep, cache: CacheDep, limit: int = Query(25, ge=1, le=100),
                offset: int = Query(0, ge=0), search: str | None = Query(None, max_length=100)) -> dict:
    """Users with conversations, requests, failures, tokens and last activity."""
    return await _cached(cache, f"users:{limit}:{offset}:{search}",
                         lambda: svc.users(session, limit, offset, search))


@router.get("/users/{user_id}")
async def user_detail(user_id: uuid.UUID, _: AdminUser, session: SessionDep, cache: CacheDep,
                      period_from: datetime | None = FROM, period_to: datetime | None = TO) -> dict:
    """One user's usage by day and by LLM role."""
    data = await _cached(cache, f"user:{user_id}:{period_from}:{period_to}",
                         lambda: svc.user_detail(session, user_id, period_from, period_to))
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return data


@router.get("/runs")
async def runs(_: AdminUser, session: SessionDep, cache: CacheDep,
               status_filter: Literal["running", "succeeded", "failed", "cancelled"] | None = Query(None, alias="status"),
               limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict:
    """Recent runs across all users (status=failed for the error log)."""
    return await _cached(cache, f"runs:{status_filter}:{limit}:{offset}",
                         lambda: svc.runs(session, status_filter, limit, offset))


@router.get("/runs/{run_id}")
async def run_detail(run_id: uuid.UUID, _: AdminUser, session: SessionDep) -> dict:
    """Any run with its LLM calls and full event timeline (not cached: used for debugging)."""
    data = await svc.run_detail(session, run_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return data

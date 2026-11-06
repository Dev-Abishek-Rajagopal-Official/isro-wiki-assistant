"""Usage: agent requests, LLM calls and token consumption (own tracking of Azure-reported usage)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CacheDep, CurrentUser, SessionDep
from app.core.config import get_settings
from app.schemas.usage import GroupBy, UsageReport
from app.services.repository import get_conversation, get_thread
from app.services.usage import usage_report

router = APIRouter(prefix="/usage", tags=["usage"])

FROM = Query(None, alias="from", description="ISO datetime, inclusive")
TO = Query(None, alias="to", description="ISO datetime, exclusive")


async def _cached(cache, key: str, producer) -> UsageReport:
    data = await cache.get_or_set(key, get_settings().usage_cache_ttl_s,
                                  lambda: _dump(producer()))
    return UsageReport.model_validate(data)


async def _dump(coro) -> dict:
    return (await coro).model_dump(mode="json")


@router.get("/me", response_model=UsageReport)
async def my_usage(user: CurrentUser, session: SessionDep, cache: CacheDep, period_from: datetime | None = FROM,
                   period_to: datetime | None = TO, group_by: GroupBy = "none") -> UsageReport:
    """All of the user's usage: requests (runs), success/error rates, latency percentiles, LLM calls and
    tokens (input / output / reasoning / cached), optionally grouped by day, model, role, agent node,
    conversation or thread. Cached for a minute."""
    key = f"usage:{user.id}:me:{period_from}:{period_to}:{group_by}"
    return await _cached(cache, key, lambda: usage_report(session, user_id=user.id, period_from=period_from,
                                                          period_to=period_to, group_by=group_by))


@router.get("/conversations/{conversation_id}", response_model=UsageReport)
async def conversation_usage(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, cache: CacheDep,
                             period_from: datetime | None = FROM, period_to: datetime | None = TO,
                             group_by: GroupBy = "thread") -> UsageReport:
    conv = await get_conversation(session, user.id, conversation_id)
    key = f"usage:{user.id}:conv:{conv.id}:{period_from}:{period_to}:{group_by}"
    return await _cached(cache, key, lambda: usage_report(session, user_id=user.id, period_from=period_from,
                                                          period_to=period_to, group_by=group_by,
                                                          conversation_id=conv.id))


@router.get("/threads/{thread_id}", response_model=UsageReport)
async def thread_usage(thread_id: uuid.UUID, user: CurrentUser, session: SessionDep, cache: CacheDep,
                       period_from: datetime | None = FROM, period_to: datetime | None = TO,
                       group_by: GroupBy = "role") -> UsageReport:
    thread = await get_thread(session, user.id, thread_id)
    key = f"usage:{user.id}:thread:{thread.id}:{period_from}:{period_to}:{group_by}"
    return await _cached(cache, key, lambda: usage_report(session, user_id=user.id, period_from=period_from,
                                                          period_to=period_to, group_by=group_by,
                                                          thread_id=thread.id))

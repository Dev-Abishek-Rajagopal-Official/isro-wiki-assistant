"""Usage aggregation over runs and llm_calls (per user, optionally per conversation / thread)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, LlmCall, Run, Thread
from app.schemas.usage import GroupBy, RateLimit, RunStats, TokenCounts, UsageGroup, UsageReport

TOKEN_COLS = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")


def _token_columns():
    return [func.count(LlmCall.id).label("llm_calls"),
            *[func.coalesce(func.sum(getattr(LlmCall, c)), 0).label(c) for c in TOKEN_COLS],
            func.avg(LlmCall.seconds).label("avg_llm_call_seconds")]


def _tokens(row) -> dict:
    d = {"llm_calls": row.llm_calls, **{c: int(getattr(row, c)) for c in TOKEN_COLS},
         "avg_llm_call_seconds": round(row.avg_llm_call_seconds, 3) if row.avg_llm_call_seconds else None}
    d["total_tokens"] = d["input_tokens"] + d["output_tokens"]
    return d


async def usage_report(session: AsyncSession, *, user_id: uuid.UUID | None, period_from: datetime | None,
                       period_to: datetime | None, group_by: GroupBy = "none",
                       conversation_id: uuid.UUID | None = None, thread_id: uuid.UUID | None = None) -> UsageReport:
    """Usage for one user (or for everyone when ``user_id`` is None - admin), optionally scoped."""
    # ---- filters
    call_f = [LlmCall.user_id == user_id] if user_id else []
    run_f = [Run.user_id == user_id] if user_id else []
    if period_from:
        call_f.append(LlmCall.created_at >= period_from)
        run_f.append(Run.started_at >= period_from)
    if period_to:
        call_f.append(LlmCall.created_at < period_to)
        run_f.append(Run.started_at < period_to)
    if conversation_id:
        call_f.append(LlmCall.conversation_id == conversation_id)
        run_f.append(Run.thread_id.in_(select(Thread.id).where(Thread.conversation_id == conversation_id)))
    if thread_id:
        call_f.append(LlmCall.thread_id == thread_id)
        run_f.append(Run.thread_id == thread_id)
    call_where = and_(true(), *call_f)
    run_f = [true(), *run_f]

    # ---- runs (agent requests)
    r = (await session.execute(select(
        func.count(Run.id).label("requests"),
        func.count().filter(Run.status == "succeeded").label("succeeded"),
        func.count().filter(Run.status == "failed").label("failed"),
        func.count().filter(Run.status == "cancelled").label("cancelled"),
        func.count().filter(Run.input_type == "voice").label("voice"),
        func.avg(Run.seconds).label("avg"),
        func.percentile_cont(0.5).within_group(Run.seconds).label("p50"),
        func.percentile_cont(0.95).within_group(Run.seconds).label("p95"),
    ).where(and_(*run_f)))).one()
    runs = RunStats(requests=r.requests, succeeded=r.succeeded, failed=r.failed, cancelled=r.cancelled,
                    voice_requests=r.voice, error_rate=round(r.failed / r.requests, 4) if r.requests else 0.0,
                    **{k: round(v, 2) if v is not None else None
                       for k, v in (("avg_seconds", r.avg), ("p50_seconds", r.p50), ("p95_seconds", r.p95))})

    # ---- tokens
    tokens = TokenCounts(**_tokens((await session.execute(select(*_token_columns()).where(call_where))).one()))

    # ---- groups
    groups: list[UsageGroup] = []
    if group_by != "none":
        key_col, label_col, join = {
            "day": (func.date_trunc("day", LlmCall.created_at), None, None),
            "model": (LlmCall.model, None, None),
            "role": (LlmCall.role, None, None),
            "node": (LlmCall.node, None, None),
            "conversation": (LlmCall.conversation_id, Conversation.title, Conversation),
            "thread": (LlmCall.thread_id, Thread.title, Thread),
        }[group_by]
        cols = [key_col.label("key"), *([label_col.label("label")] if label_col is not None else []), *_token_columns()]
        q = select(*cols).where(call_where)
        if join is not None:
            q = q.outerjoin(join, join.id == key_col)
        q = q.group_by(key_col, *([label_col] if label_col is not None else []))
        q = q.order_by(key_col) if group_by == "day" else q.order_by(func.sum(LlmCall.input_tokens).desc())
        for row in (await session.execute(q)).all():
            key = row.key.date().isoformat() if group_by == "day" and row.key else (str(row.key) if row.key else None)
            groups.append(UsageGroup(key=key, label=getattr(row, "label", None), **_tokens(row)))

    # ---- latest Azure rate-limit headroom
    last = (await session.execute(
        select(LlmCall.ratelimit_remaining_requests, LlmCall.ratelimit_remaining_tokens, LlmCall.created_at)
        .where(call_where, LlmCall.ratelimit_remaining_tokens.is_not(None))
        .order_by(LlmCall.id.desc()).limit(1))).first()
    rate = RateLimit(remaining_requests=last[0], remaining_tokens=last[1], observed_at=last[2]) if last else None

    scope = {"user_id": str(user_id) if user_id else "all"}
    if conversation_id:
        scope["conversation_id"] = str(conversation_id)
    if thread_id:
        scope["thread_id"] = str(thread_id)
    return UsageReport(scope=scope, period_from=period_from, period_to=period_to, runs=runs, tokens=tokens,
                       group_by=group_by, groups=groups, latest_rate_limit=rate)

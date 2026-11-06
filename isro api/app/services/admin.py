"""System-wide analytics for the admin panel (all users). Results are cached in Redis by the routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import String, cast, func, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, LlmCall, Run, Thread, User
from app.services.usage import usage_report

Bucket = Literal["hour", "day", "week"]


def _period(model_ts, period_from: datetime | None, period_to: datetime | None) -> list:
    f = [true()]
    if period_from:
        f.append(model_ts >= period_from)
    if period_to:
        f.append(model_ts < period_to)
    return f


async def overview(session: AsyncSession, period_from: datetime | None, period_to: datetime | None) -> dict:
    """Headline numbers: users, activity, conversations, requests, latency, tokens, rate-limit headroom."""
    now = datetime.now(timezone.utc)
    users_total = await session.scalar(select(func.count(User.id)))
    active = {}
    for label, since in (("active_today", now - timedelta(days=1)), ("active_7d", now - timedelta(days=7)),
                         ("active_30d", now - timedelta(days=30))):
        active[label] = await session.scalar(select(func.count(func.distinct(Run.user_id)))
                                             .where(Run.started_at >= since))
    convs = await session.scalar(select(func.count(Conversation.id))
                                 .where(*_period(Conversation.created_at, period_from, period_to)))
    threads = await session.scalar(select(func.count(Thread.id))
                                   .where(*_period(Thread.created_at, period_from, period_to)))
    report = await usage_report(session, user_id=None, period_from=period_from, period_to=period_to)
    return {"users": {"total": users_total, **active}, "conversations": convs, "threads": threads,
            "runs": report.runs.model_dump(), "tokens": report.tokens.model_dump(),
            "latest_rate_limit": report.latest_rate_limit.model_dump(mode="json") if report.latest_rate_limit else None}


async def timeseries(session: AsyncSession, bucket: Bucket, period_from: datetime | None,
                     period_to: datetime | None) -> list[dict]:
    """Per time bucket: requests, failures, error rate, latency (avg / p95), voice requests, tokens."""
    rb = func.date_trunc(bucket, Run.started_at)
    runs = (await session.execute(
        select(rb.label("b"), func.count(Run.id).label("requests"),
               func.count().filter(Run.status == "failed").label("failed"),
               func.count().filter(Run.input_type == "voice").label("voice"),
               func.avg(Run.seconds).label("avg_s"),
               func.percentile_cont(0.95).within_group(Run.seconds).label("p95_s"))
        .where(*_period(Run.started_at, period_from, period_to)).group_by(rb).order_by(rb))).all()
    cb = func.date_trunc(bucket, LlmCall.created_at)
    calls = {r.b: r for r in (await session.execute(
        select(cb.label("b"), func.count(LlmCall.id).label("llm_calls"),
               func.coalesce(func.sum(LlmCall.input_tokens), 0).label("inp"),
               func.coalesce(func.sum(LlmCall.output_tokens), 0).label("out"),
               func.coalesce(func.sum(LlmCall.reasoning_tokens), 0).label("rsn"))
        .where(*_period(LlmCall.created_at, period_from, period_to)).group_by(cb))).all()}
    out = []
    for b in sorted({r.b for r in runs} | set(calls)):
        r = next((x for x in runs if x.b == b), None)
        c = calls.get(b)
        req = r.requests if r else 0
        out.append({"bucket": b.isoformat(), "requests": req, "failed": r.failed if r else 0,
                    "error_rate": round(r.failed / req, 4) if r and req else 0.0, "voice": r.voice if r else 0,
                    "avg_seconds": round(r.avg_s, 2) if r and r.avg_s else None,
                    "p95_seconds": round(r.p95_s, 2) if r and r.p95_s else None,
                    "llm_calls": c.llm_calls if c else 0, "input_tokens": int(c.inp) if c else 0,
                    "output_tokens": int(c.out) if c else 0, "reasoning_tokens": int(c.rsn) if c else 0})
    return out


async def agents(session: AsyncSession, period_from: datetime | None, period_to: datetime | None) -> dict:
    """Which agents are used, which routes the router takes, average hops, tokens per agent node."""
    period = _period(Run.started_at, period_from, period_to)
    agent = func.jsonb_array_elements_text(Run.agents_used).table_valued("value").alias("a")
    usage = (await session.execute(
        select(agent.c.value.label("agent"), func.count().label("runs"))
        .select_from(Run).join(agent, true()).where(*period).group_by(agent.c.value)
        .order_by(func.count().desc()))).all()
    route = func.coalesce(cast(Run.agents_used, String), "[]")
    routes = (await session.execute(
        select(route.label("route"), func.count().label("runs"), func.avg(Run.seconds).label("avg_s"))
        .where(*period, Run.status == "succeeded").group_by(route).order_by(func.count().desc()).limit(10))).all()
    avg_hops = await session.scalar(
        select(func.avg(func.jsonb_array_length(Run.agents_used))).where(*period, Run.agents_used.is_not(None)))
    nodes = (await session.execute(
        select(LlmCall.node, func.count(LlmCall.id).label("calls"),
               func.coalesce(func.sum(LlmCall.input_tokens + LlmCall.output_tokens), 0).label("tokens"),
               func.avg(LlmCall.seconds).label("avg_s"))
        .where(*_period(LlmCall.created_at, period_from, period_to)).group_by(LlmCall.node)
        .order_by(func.count(LlmCall.id).desc()))).all()
    return {
        "agent_usage": [{"agent": r.agent, "runs": r.runs} for r in usage],
        "routes": [{"route": ["router", *json.loads(r.route), "final_agent"], "runs": r.runs,
                    "avg_seconds": round(r.avg_s, 2) if r.avg_s else None} for r in routes],
        "avg_agents_per_run": round(float(avg_hops), 2) if avg_hops is not None else None,
        "llm_by_node": [{"node": r.node, "calls": r.calls, "tokens": int(r.tokens),
                         "avg_seconds": round(r.avg_s, 2) if r.avg_s else None} for r in nodes],
    }


async def tools(session: AsyncSession, period_from: datetime | None, period_to: datetime | None) -> list[dict]:
    """MCP tool calls (from tool_result events of API runs): count, failures, empty results, avg duration."""
    sql = text("""
        SELECT e.node AS agent, e.payload->>'tool' AS tool, count(*) AS calls,
               count(*) FILTER (WHERE (e.payload->>'ok')::boolean IS NOT TRUE) AS failed,
               count(*) FILTER (WHERE (e.payload->>'empty')::boolean IS TRUE) AS empty,
               avg(NULLIF(e.payload->>'duration_ms', '')::numeric) AS avg_ms
        FROM agent_events e JOIN runs r ON r.id = e.run_id
        WHERE e.event_type = 'tool_result'
          AND (CAST(:f AS timestamptz) IS NULL OR e.ts >= CAST(:f AS timestamptz))
          AND (CAST(:t AS timestamptz) IS NULL OR e.ts <  CAST(:t AS timestamptz))
        GROUP BY e.node, e.payload->>'tool' ORDER BY calls DESC""")
    rows = (await session.execute(sql, {"f": period_from, "t": period_to})).all()
    return [{"agent": r.agent, "tool": r.tool, "calls": r.calls, "failed": r.failed, "empty": r.empty,
             "failure_rate": round(r.failed / r.calls, 4) if r.calls else 0.0,
             "avg_ms": round(float(r.avg_ms)) if r.avg_ms is not None else None} for r in rows]


async def models(session: AsyncSession, period_from: datetime | None, period_to: datetime | None) -> dict:
    by_model = await usage_report(session, user_id=None, period_from=period_from, period_to=period_to,
                                  group_by="model")
    by_role = await usage_report(session, user_id=None, period_from=period_from, period_to=period_to,
                                 group_by="role")
    return {"by_model": [g.model_dump() for g in by_model.groups], "by_role": [g.model_dump() for g in by_role.groups]}


async def users(session: AsyncSession, limit: int, offset: int, search: str | None) -> dict:
    """Users with their activity: conversations, requests, tokens, last active."""
    conv_n = select(func.count(Conversation.id)).where(Conversation.user_id == User.id).scalar_subquery()
    run_n = select(func.count(Run.id)).where(Run.user_id == User.id).scalar_subquery()
    failed_n = select(func.count(Run.id)).where(Run.user_id == User.id, Run.status == "failed").scalar_subquery()
    tok = select(func.coalesce(func.sum(LlmCall.input_tokens + LlmCall.output_tokens), 0)) \
        .where(LlmCall.user_id == User.id).scalar_subquery()
    last = select(func.max(Run.started_at)).where(Run.user_id == User.id).scalar_subquery()
    q = select(User, conv_n.label("conversations"), run_n.label("requests"), failed_n.label("failed"),
               tok.label("tokens"), last.label("last_active"))
    if search:
        like = f"%{search.lower()}%"
        q = q.where((func.lower(User.email).like(like)) | (func.lower(User.full_name).like(like)))
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(last.desc().nulls_last(), User.created_at.desc())
                                  .limit(limit).offset(offset))).all()
    return {"total": total, "items": [
        {"id": str(u.id), "email": u.email, "full_name": u.full_name, "is_active": u.is_active,
         "created_at": u.created_at.isoformat(), "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
         "conversations": c, "requests": r, "failed": f, "tokens": int(t),
         "last_active": la.isoformat() if la else None} for u, c, r, f, t, la in rows]}


async def user_detail(session: AsyncSession, user_id: uuid.UUID, period_from, period_to) -> dict | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    report = await usage_report(session, user_id=user_id, period_from=period_from, period_to=period_to,
                                group_by="day")
    by_role = await usage_report(session, user_id=user_id, period_from=period_from, period_to=period_to,
                                 group_by="role")
    return {"user": {"id": str(user.id), "email": user.email, "full_name": user.full_name,
                     "is_active": user.is_active, "created_at": user.created_at.isoformat()},
            "usage": report.model_dump(mode="json"), "by_role": [g.model_dump() for g in by_role.groups]}


async def runs(session: AsyncSession, status: str | None, limit: int, offset: int) -> dict:
    """Recent runs across users (e.g. status=failed for the error log)."""
    q = (select(Run, User.email, Thread.title, Thread.conversation_id)
         .join(User, User.id == Run.user_id).join(Thread, Thread.id == Run.thread_id))
    if status:
        q = q.where(Run.status == status)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(Run.started_at.desc()).limit(limit).offset(offset))).all()
    return {"total": total, "items": [
        {"id": str(r.id), "thread_id": str(r.thread_id), "conversation_id": str(cid), "thread_title": title,
         "user_email": email, "question": r.question, "input_type": r.input_type, "status": r.status,
         "error": r.error, "started_at": r.started_at.isoformat(), "seconds": r.seconds,
         "agents_used": r.agents_used, "tokens": r.input_tokens + r.output_tokens}
        for r, email, title, cid in rows]}


async def run_detail(session: AsyncSession, run_id: uuid.UUID) -> dict | None:
    """Any run with its LLM calls and its full stored event timeline (for debugging)."""
    run = await session.get(Run, run_id)
    if run is None:
        return None
    calls = (await session.execute(select(LlmCall).where(LlmCall.run_id == run_id).order_by(LlmCall.id))).scalars()
    events = (await session.execute(text(
        "SELECT id, ts, seq, node, event_type, payload FROM agent_events WHERE run_id = :r ORDER BY seq"),
        {"r": run_id})).all()
    user = await session.get(User, run.user_id)
    return {
        "run": {c.name: getattr(run, c.name) for c in Run.__table__.columns},
        "user_email": user.email if user else None,
        "llm_calls": [{k: getattr(c, k) for k in ("node", "role", "model", "input_tokens", "output_tokens",
                                                   "reasoning_tokens", "cached_tokens", "seconds")} for c in calls],
        "events": [{"id": e.id, "ts": e.ts.isoformat(), "seq": e.seq, "node": e.node, "event_type": e.event_type,
                    "payload": e.payload} for e in events],
    }

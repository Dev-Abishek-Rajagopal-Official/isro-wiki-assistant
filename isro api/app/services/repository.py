"""Ownership-checked lookups. Anything not owned by the user is reported as 404 (no existence leak)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Run, Thread


async def get_conversation(session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conv


async def get_thread(session: AsyncSession, user_id: uuid.UUID, thread_id: uuid.UUID) -> Thread:
    thread = await session.get(Thread, thread_id)
    if thread is None or thread.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "thread not found")
    return thread


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None or run.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


async def thread_counts(session: AsyncSession, conversation_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not conversation_ids:
        return {}
    rows = await session.execute(
        select(Thread.conversation_id, func.count()).where(Thread.conversation_id.in_(conversation_ids),
                                                           Thread.archived.is_(False))
        .group_by(Thread.conversation_id))
    return dict(rows.all())

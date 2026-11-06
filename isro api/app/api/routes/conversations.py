"""Conversations (a user's workspaces) and the threads inside them."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, tuple_

from app.api.deps import CurrentUser, SessionDep
from app.db.models import Conversation, Thread
from app.schemas.conversations import (ConversationCreate, ConversationDetail, ConversationOut, ConversationPage,
                                       ConversationUpdate, ThreadCreate, ThreadOut)
from app.services.repository import get_conversation, thread_counts

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _out(conv: Conversation, count: int, model=ConversationOut, **extra):
    return model.model_validate({**{c: getattr(conv, c) for c in ConversationOut.model_fields if c != "thread_count"},
                                 "thread_count": count, **extra})


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationCreate, user: CurrentUser, session: SessionDep) -> ConversationOut:
    """Create a conversation. Without a title, one is generated from the first question asked in it."""
    conv = Conversation(user_id=user.id, title=body.title, title_source="user" if body.title else None)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return _out(conv, 0)


def _encode_cursor(activity: datetime, conv_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([activity.isoformat(), str(conv_id)]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, cid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(ts), uuid.UUID(cid)
    except (ValueError, TypeError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid cursor") from e


@router.get("", response_model=ConversationPage)
async def list_conversations(user: CurrentUser, session: SessionDep, include_archived: bool = False,
                             limit: int = Query(10, ge=1, le=100),
                             cursor: str | None = Query(None, description="next_cursor of the previous page")
                             ) -> ConversationPage:
    """The user's conversations, most recently active first, ``limit`` per page.

    Keyset pagination on (last activity, id): pages stay consistent while conversations move to the top."""
    activity = func.coalesce(Conversation.last_activity_at, Conversation.created_at)
    q = select(Conversation, activity.label("activity")).where(Conversation.user_id == user.id)
    if not include_archived:
        q = q.where(Conversation.archived.is_(False))
    if cursor:
        ts, cid = _decode_cursor(cursor)
        q = q.where(tuple_(activity, Conversation.id) < tuple_(ts, cid))
    rows = (await session.execute(q.order_by(activity.desc(), Conversation.id.desc()).limit(limit + 1))).all()
    page, more = rows[:limit], len(rows) > limit
    counts = await thread_counts(session, [c.id for c, _ in page])
    return ConversationPage(items=[_out(c, counts.get(c.id, 0)) for c, _ in page],
                            next_cursor=_encode_cursor(page[-1][1], page[-1][0].id) if more else None)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_detail(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    conv = await get_conversation(session, user.id, conversation_id)
    threads = (await session.execute(select(Thread).where(Thread.conversation_id == conv.id)
                                     .order_by(Thread.created_at))).scalars().all()
    active = [ThreadOut.model_validate(t) for t in threads if not t.archived]
    return _out(conv, len(active), ConversationDetail, threads=active)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser,
                              session: SessionDep) -> ConversationOut:
    """Rename (title_source becomes 'user') and/or archive / unarchive."""
    conv = await get_conversation(session, user.id, conversation_id)
    if body.title is not None:
        conv.title, conv.title_source = body.title, "user"
    if body.archived is not None:
        conv.archived = body.archived
    await session.commit()
    await session.refresh(conv)
    counts = await thread_counts(session, [conv.id])
    return _out(conv, counts.get(conv.id, 0))


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    """Soft delete (archive); history stays available via include_archived."""
    conv = await get_conversation(session, user.id, conversation_id)
    conv.archived = True
    await session.commit()


@router.post("/{conversation_id}/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(conversation_id: uuid.UUID, body: ThreadCreate, user: CurrentUser,
                        session: SessionDep) -> Thread:
    """Start a new thread (independent agent memory) inside a conversation."""
    conv = await get_conversation(session, user.id, conversation_id)
    thread = Thread(conversation_id=conv.id, user_id=user.id, title=body.title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


@router.get("/{conversation_id}/threads", response_model=list[ThreadOut])
async def list_threads(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep,
                       include_archived: bool = False) -> list[Thread]:
    conv = await get_conversation(session, user.id, conversation_id)
    q = select(Thread).where(Thread.conversation_id == conv.id)
    if not include_archived:
        q = q.where(Thread.archived.is_(False))
    return list((await session.execute(q.order_by(Thread.created_at))).scalars().all())

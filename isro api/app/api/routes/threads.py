"""
Threads: detail, history (runs, events, AgentState snapshots) and the REST ask endpoints.
(Streaming happens over the WebSocket; REST ask runs are also published live to subscribed sockets.)
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import LlmCall, Run, Thread
from app.schemas.conversations import AskRequest, RunOut, ThreadDetail, ThreadOut, ThreadUpdate
from app.services.repository import get_run, get_thread
from app.services.runs import ThreadBusy

router = APIRouter(tags=["threads"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def thread_detail(thread_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep):
    """Thread with its conversation turns, current AgentState, token usage and runs."""
    thread = await get_thread(session, user.id, thread_id)
    runs = (await session.execute(select(Run).where(Run.thread_id == thread.id)
                                  .order_by(Run.started_at))).scalars().all()
    state: dict[str, Any] = {}
    runtime = request.app.state.agent
    if runtime.ready:
        state = await runtime.service.get_state(str(thread.id))
    messages = state.pop("messages", [])
    return ThreadDetail.model_validate({**ThreadOut.model_validate(thread).model_dump(), "messages": messages,
                                        "agent_state": state, "thread_usage": state.get("thread_usage", {}),
                                        "runs": [RunOut.model_validate(r) for r in runs]})


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(thread_id: uuid.UUID, body: ThreadUpdate, user: CurrentUser, session: SessionDep) -> Thread:
    thread = await get_thread(session, user.id, thread_id)
    if body.title is not None:
        thread.title = body.title
    if body.archived is not None:
        thread.archived = body.archived
    await session.commit()
    await session.refresh(thread)
    return thread


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_thread(thread_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    thread = await get_thread(session, user.id, thread_id)
    thread.archived = True
    await session.commit()


@router.get("/threads/{thread_id}/runs", response_model=list[RunOut])
async def thread_runs(thread_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[Run]:
    thread = await get_thread(session, user.id, thread_id)
    return list((await session.execute(select(Run).where(Run.thread_id == thread.id)
                                       .order_by(Run.started_at))).scalars().all())


@router.get("/threads/{thread_id}/events")
async def thread_events(thread_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep,
                        after_id: int = Query(0, ge=0), run_id: uuid.UUID | None = None) -> list[dict]:
    """Stored event log of the thread (every AgentState change and progress event), oldest first.
    Use ``after_id`` to fetch only newer events (e.g. after a reconnect)."""
    thread = await get_thread(session, user.id, thread_id)
    service = request.app.state.agent.require()
    return await service.history(str(thread.id), str(run_id) if run_id else None, after_id)


@router.get("/threads/{thread_id}/states")
async def thread_states(thread_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep,
                        limit: int = Query(200, ge=1, le=1000)) -> list[dict]:
    """AgentState snapshot after every graph step (LangGraph checkpoints), oldest first."""
    thread = await get_thread(session, user.id, thread_id)
    return await request.app.state.agent.require().state_history(str(thread.id), limit=limit)


@router.get("/runs/{run_id}")
async def run_detail(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict:
    """One run with every LLM call it made (role, model, tokens, latency, rate-limit headroom)."""
    run = await get_run(session, user.id, run_id)
    calls = (await session.execute(select(LlmCall).where(LlmCall.run_id == run.id)
                                   .order_by(LlmCall.id))).scalars().all()
    return {**RunOut.model_validate(run).model_dump(mode="json"),
            "llm_call_details": [{c: getattr(call, c) for c in ("node", "role", "model", "input_tokens",
                                                                 "output_tokens", "reasoning_tokens", "cached_tokens",
                                                                 "seconds", "ratelimit_remaining_requests",
                                                                 "ratelimit_remaining_tokens", "created_at")}
                                 for call in calls]}


async def _run(request: Request, user, thread_id: uuid.UUID, *, question=None, audio=None) -> dict:
    runs = request.app.state.runs
    request.app.state.agent.require()
    try:
        run_id = await runs.reserve(thread_id)
    except ThreadBusy as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "a run is already in progress on this thread") from e
    return await runs.execute(run_id=run_id, user_id=user.id, thread_id=thread_id, question=question, audio=audio)


@router.post("/threads/{thread_id}/ask")
async def ask(thread_id: uuid.UUID, body: AskRequest, request: Request, user: CurrentUser,
              session: SessionDep) -> dict:
    """Ask a question and wait for the full answer (non-streaming alternative to the WebSocket)."""
    thread = await get_thread(session, user.id, thread_id)
    if thread.archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "thread is archived")
    return await _run(request, user, thread.id, question=body.question)


@router.post("/threads/{thread_id}/ask-audio")
async def ask_audio(thread_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep,
                    audio: UploadFile = File(..., description="WAV / MP3 / OGG recording of the question")) -> dict:
    """Ask by voice: Azure speech-to-text, then the same agent run."""
    thread = await get_thread(session, user.id, thread_id)
    data = await audio.read()
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "audio must be 1 byte - 25 MB")
    return await _run(request, user, thread.id,
                      audio=(data, audio.filename or "audio.wav", audio.content_type or "audio/wav"))

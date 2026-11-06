"""
WebSocket ``/ws`` - streaming answers and live AgentState for any number of threads on one socket.

Protocol (JSON messages)
  client -> server
    {"type": "auth", "token": "<JWT>"}                          first message, within WS_AUTH_TIMEOUT_S; also
                                                                 used to re-authenticate after auth_expired
    {"type": "ask", "thread_id": "...", "question": "...", "client_msg_id": "..."}
    {"type": "ask_audio", "thread_id": "...", "audio_b64": "...", "filename": "q.wav",
     "content_type": "audio/wav", "client_msg_id": "..."}
    {"type": "subscribe", "thread_id": "...", "after_id": 0}    replay stored events after after_id, then live
    {"type": "unsubscribe", "thread_id": "..."}
    {"type": "cancel", "run_id": "..."}
    {"type": "ping"}
  server -> client
    auth_ok | auth_expired | error | pong | accepted {client_msg_id, run_id, thread_id} | subscribed | replay_done
    run messages: run_started, transcribing, transcribed, router_decision, agent_progress (step=...),
                  llm_call, state_update, state (full AgentState), token, final_answer, run_finished,
                  run_cancelled, error
    user messages: conversation_titled
  Run messages share one envelope: {type, thread_id, run_id, seq, node, event_id, ts, data}.
  Replayed messages carry "replay": true. Clients should de-duplicate by event_id.

Close codes: 4401 authentication failed / missing, 4400 bad first message.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.api.deps import AuthError, AuthUser, authenticate_token
from app.core.config import get_settings
from app.db.models import Thread
from app.services.runs import ThreadBusy, to_ws_message

router = APIRouter()
log = logging.getLogger(__name__)

MAX_AUDIO_B64 = 34 * 1024 * 1024  # ~25 MB audio


class Connection:
    """One authenticated WebSocket: serialised sends, its pub/sub subscription and its run tasks."""

    def __init__(self, ws: WebSocket, app) -> None:
        self.ws, self.app = ws, app
        self.user: AuthUser | None = None
        self.send_lock = asyncio.Lock()
        self.subscription = None
        self.tasks: set[asyncio.Task] = set()

    async def send(self, message: dict) -> None:
        async with self.send_lock:
            await self.ws.send_json(jsonable_encoder(message))

    async def error(self, detail: str, **extra) -> None:
        await self.send({"type": "error", "data": {"error": detail}, **extra})

    async def authenticate(self, token: str | None) -> bool:
        s = self.app.state
        try:
            self.user = await authenticate_token(token or "", db=s.db, tokens=s.tokens, cache=s.cache)
        except AuthError as e:
            await self.send({"type": "auth_failed", "data": {"error": e.detail}})
            return False
        await self.send({"type": "auth_ok", "data": {"user_id": str(self.user.id), "email": self.user.email,
                                                     "expires_at": self.user.claims["exp"]}})
        return True

    def token_expired(self) -> bool:
        return self.user is None or self.user.claims["exp"] <= time.time()

    async def owned_thread(self, raw_id) -> Thread | None:
        try:
            tid = uuid.UUID(str(raw_id))
        except ValueError:
            return None
        async with self.app.state.db.sessionmaker() as session:
            thread = await session.get(Thread, tid)
        return thread if thread is not None and thread.user_id == self.user.id else None

    # ------------------------------------------------------------------ handlers
    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "ping":
            await self.send({"type": "pong"})
        elif kind == "auth":
            await self.authenticate(msg.get("token"))
        elif kind in ("ask", "ask_audio"):
            await self.start_run(msg)
        elif kind == "subscribe":
            await self.subscribe(msg)
        elif kind == "unsubscribe":
            await self.subscription.remove_thread(str(msg.get("thread_id")))
            await self.send({"type": "unsubscribed", "thread_id": msg.get("thread_id")})
        elif kind == "cancel":
            ok = self.app.state.runs.cancel(str(msg.get("run_id")))
            await self.send({"type": "cancel_ack", "run_id": msg.get("run_id"), "data": {"cancelled": ok}})
        else:
            await self.error(f"unknown message type {kind!r}")

    async def start_run(self, msg: dict) -> None:
        cid = msg.get("client_msg_id")
        thread = await self.owned_thread(msg.get("thread_id"))
        if thread is None:
            return await self.error("thread not found", client_msg_id=cid)
        if thread.archived:
            return await self.error("thread is archived", client_msg_id=cid)
        if not self.app.state.agent.ready:
            return await self.error(f"agent unavailable: {self.app.state.agent.error}", client_msg_id=cid)

        question, audio = None, None
        if msg["type"] == "ask":
            question = (msg.get("question") or "").strip()
            if not question or len(question) > 4000:
                return await self.error("question must be 1-4000 characters", client_msg_id=cid)
        else:
            raw = msg.get("audio_b64") or ""
            if not raw or len(raw) > MAX_AUDIO_B64:
                return await self.error("audio_b64 missing or too large", client_msg_id=cid)
            try:
                audio = (base64.b64decode(raw, validate=True), msg.get("filename") or "audio.wav",
                         msg.get("content_type") or "audio/wav")
            except (binascii.Error, ValueError):
                return await self.error("audio_b64 is not valid base64", client_msg_id=cid)

        runs = self.app.state.runs
        try:
            run_id = await runs.reserve(thread.id)
        except ThreadBusy:
            return await self.send({"type": "busy", "thread_id": str(thread.id), "client_msg_id": cid,
                                    "data": {"error": "a run is already in progress on this thread"}})
        await self.subscription.add_thread(str(thread.id))   # receive this run's messages via pub/sub
        await self.send({"type": "accepted", "client_msg_id": cid, "run_id": run_id, "thread_id": str(thread.id)})
        task = asyncio.create_task(runs.execute(run_id=run_id, user_id=self.user.id, thread_id=thread.id,
                                                question=question, audio=audio), name=f"run-{run_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def subscribe(self, msg: dict) -> None:
        thread = await self.owned_thread(msg.get("thread_id"))
        if thread is None:
            return await self.error("thread not found")
        tid = str(thread.id)
        await self.subscription.add_thread(tid)               # live first, so nothing is missed
        await self.send({"type": "subscribed", "thread_id": tid})
        if self.app.state.agent.ready:
            events = await self.app.state.agent.service.history(tid, after_id=int(msg.get("after_id") or 0))
            for ev in events:
                await self.send({**to_ws_message(ev), "replay": True})
            await self.send({"type": "replay_done", "thread_id": tid, "data": {"count": len(events)}})


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws, ws.app)
    try:
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=get_settings().ws_auth_timeout_s)
        except (asyncio.TimeoutError, ValueError):
            await ws.close(code=4401, reason="authentication required")
            return
        if first.get("type") != "auth" or not await conn.authenticate(first.get("token")):
            await ws.close(code=4401, reason="authentication failed")
            return

        conn.subscription = ws.app.state.hub.subscription(str(conn.user.id), conn.send)
        await conn.subscription.start()
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                await conn.error("messages must be JSON objects")
                continue
            if not isinstance(msg, dict):
                await conn.error("messages must be JSON objects")
                continue
            if msg.get("type") != "auth" and conn.token_expired():
                await conn.send({"type": "auth_expired", "data": {"error": "access token expired; send auth"}})
                continue
            try:
                await conn.handle(msg)
            except Exception as e:  # noqa: BLE001 - one bad message must not kill the socket
                log.exception("ws message failed")
                await conn.error(f"{type(e).__name__}: {str(e)[:200]}")
    except WebSocketDisconnect:
        pass
    finally:
        # Runs keep going after a disconnect (results are stored); only the live forwarding stops.
        if conn.subscription is not None:
            await conn.subscription.close()

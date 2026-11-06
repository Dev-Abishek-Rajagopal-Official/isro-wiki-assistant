"""
Run execution shared by the WebSocket and REST endpoints.

For one user question on a thread:
  1. take the per-thread run lock in Redis (one active run per thread, across API instances)
  2. create the ``runs`` row; set the thread title / conversation activity; start conversation-title
     generation in the background if the conversation has no name yet
  3. (voice) transcribe with Azure Speech
  4. stream the agent (orchestrator persists events to ``agent_events``); every event is converted to a
     WebSocket message and published to the thread channel; ``llm_call`` events go to ``llm_calls``
  5. finalise the run (status, answer, agents used, token totals) and release the lock
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from orchestrator.speech import transcribe
from sqlalchemy import update

from app.db.models import Conversation, LlmCall, Run, Thread
from app.services.titles import LLM_CALL_FIELDS, title_conversation

log = logging.getLogger(__name__)

# orchestrator event types reported to clients as {"type": "agent_progress", "step": <event type>}
PROGRESS_STEPS = {"agent_started", "query_rewritten", "tool_called", "tool_result", "agent_content"}

_UNLOCK = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class ThreadBusy(Exception):
    """Another run is already active on this thread."""


def to_ws_message(event: dict) -> dict:
    """Orchestrator event -> WebSocket message (one uniform envelope)."""
    et = event["event_type"]
    msg = {"type": "agent_progress" if et in PROGRESS_STEPS else et,
           "thread_id": event.get("thread_id"), "run_id": event.get("run_id"), "seq": event.get("seq"),
           "node": event.get("node"), "event_id": event.get("id"), "ts": event.get("ts"),
           "data": event.get("payload", {})}
    if et in PROGRESS_STEPS:
        msg["step"] = et
    return msg


class RunService:
    def __init__(self, *, db, redis, hub, agent, lock_ttl_s: int) -> None:
        self.db, self.redis, self.hub, self.agent = db, redis, hub, agent
        self.lock_ttl_s = lock_ttl_s
        self.active: dict[str, asyncio.Task] = {}        # run_id -> task (for cancel, this instance)
        self._background: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ public API
    async def reserve(self, thread_id: uuid.UUID) -> str:
        """Take the thread's run lock and return a new run id (raises ThreadBusy)."""
        run_id = str(uuid.uuid4())
        if not await self.redis.set(f"lock:run:{thread_id}", run_id, nx=True, ex=self.lock_ttl_s):
            raise ThreadBusy(str(thread_id))
        return run_id

    async def execute(self, *, run_id: str, user_id: uuid.UUID, thread_id: uuid.UUID, question: str | None = None,
                      audio: tuple[bytes, str, str] | None = None) -> dict:
        """Run one question (text, or audio=(bytes, filename, content_type)) on a thread. The caller must
        have reserved ``run_id`` with ``reserve``; the lock is always released here."""
        service = self.agent.require()
        self.active[run_id] = asyncio.current_task()
        result = {"run_id": run_id, "status": "failed", "answer": "", "sources": [], "agents_used": [],
                  "run_usage": {}, "thread_usage": {}, "seconds": None, "transcript": None}
        input_type, transcript = ("voice" if audio else "text"), None
        try:
            if audio:
                await self._publish(thread_id, {"type": "transcribing", "run_id": run_id})
                transcript = await transcribe(*audio)
                if not transcript["text"]:
                    raise ValueError("no speech recognised in the audio")
                question = transcript["text"]
                result["transcript"] = transcript
                await self._publish(thread_id, {"type": "transcribed", "run_id": run_id, "data": transcript})
            conversation_id = await self._open_run(run_id, user_id, thread_id, question, input_type, transcript)

            async for event in service.stream(question, str(thread_id), run_id=run_id, input_type=input_type,
                                              transcript=transcript):
                await self._publish(thread_id, to_ws_message(event))
                await self._consume(event, result, user_id, thread_id, conversation_id)
            result["status"] = "succeeded"
        except asyncio.CancelledError:
            result["status"] = "cancelled"
            await self._publish(thread_id, {"type": "run_cancelled", "run_id": run_id})
            raise
        except Exception as e:  # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {str(e)[:500]}"
            log.exception("run %s failed", run_id)
            await self._publish(thread_id, {"type": "error", "run_id": run_id, "data": {"error": result["error"]}})
        finally:
            await self._close_run(run_id, result)
            self.active.pop(run_id, None)
            await self.redis.eval(_UNLOCK, 1, f"lock:run:{thread_id}", run_id)
        return result

    def cancel(self, run_id: str) -> bool:
        task = self.active.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    # ------------------------------------------------------------------ internals
    async def _publish(self, thread_id: uuid.UUID, message: dict) -> None:
        message.setdefault("thread_id", str(thread_id))
        await self.hub.publish_thread(str(thread_id), message)

    async def _open_run(self, run_id, user_id, thread_id, question, input_type, transcript) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        async with self.db.sessionmaker() as session:
            thread = await session.get(Thread, thread_id)
            conv = await session.get(Conversation, thread.conversation_id)
            session.add(Run(id=uuid.UUID(run_id), thread_id=thread_id, user_id=user_id, question=question,
                            input_type=input_type, transcript=transcript, status="running"))
            if not thread.title:
                thread.title = question[:200]
            thread.last_run_at = now
            conv.last_activity_at = now
            needs_title = not conv.title
            conversation_id = conv.id
            await session.commit()
        # one title generation per conversation, even when several threads start at the same moment
        if needs_title and await self.redis.set(f"lock:title:{conversation_id}", run_id, nx=True, ex=300):
            task = asyncio.create_task(title_conversation(
                sessionmaker=self.db.sessionmaker, hub=self.hub, user_id=user_id, conversation_id=conversation_id,
                thread_id=thread_id, question=question))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return conversation_id

    async def _consume(self, event: dict, result: dict, user_id, thread_id, conversation_id) -> None:
        et, p = event["event_type"], event.get("payload", {})
        if et == "llm_call":
            async with self.db.sessionmaker() as session:
                session.add(LlmCall(run_id=uuid.UUID(event["run_id"]), thread_id=thread_id,
                                    conversation_id=conversation_id, user_id=user_id, node=event.get("node"),
                                    **{k: p[k] for k in p if k in LLM_CALL_FIELDS}))
                await session.commit()
        elif et == "final_answer":
            result["answer"], result["sources"] = p.get("answer", ""), p.get("sources", [])
        elif et == "run_finished":
            for k in ("agents_used", "run_usage", "thread_usage", "seconds"):
                result[k] = p.get(k)

    async def _close_run(self, run_id: str, result: dict) -> None:
        usage = result.get("run_usage") or {}
        values = {"status": result["status"], "finished_at": datetime.now(timezone.utc),
                  "answer": result.get("answer") or None, "agents_used": result.get("agents_used") or [],
                  "error": result.get("error"), "seconds": result.get("seconds"),
                  **{k: usage.get(k, 0) for k in ("llm_calls", "input_tokens", "output_tokens",
                                                  "reasoning_tokens", "cached_tokens")}}
        try:
            async with self.db.sessionmaker() as session:
                await session.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(**values))
                await session.commit()
        except Exception:  # noqa: BLE001 - run row may not exist if the run failed before it was created
            log.exception("could not finalise run %s", run_id)

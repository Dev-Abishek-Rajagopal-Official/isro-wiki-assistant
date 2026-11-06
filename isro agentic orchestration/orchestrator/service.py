"""
Service facade over the LangGraph agent, used by the FastAPI layer (``isro api``).

    service = IsroAgentService()
    await service.startup()                       # once, on the application's event loop
    async for event in service.stream(question, thread_id, run_id=...):
        ...                                       # forward to the client (WebSocket)
    await service.get_state(thread_id)            # current AgentState of a thread
    await service.state_history(thread_id)        # AgentState snapshot per graph step
    await service.shutdown()

Event types yielded by ``stream`` (all persisted to ``agent_events`` before being yielded, except
``token`` and ``state`` which are live-only):

    run_started, router_decision, agent_started, query_rewritten, tool_called, tool_result,
    agent_content, llm_call, state_update, final_answer, run_finished, error   (persisted)
    token (final-answer chunk), state (full current AgentState after a node)    (live only)

Windows: the async Postgres driver needs the selector event loop (``use_selector_event_loop``) and all
MCP servers are reached over HTTP. Run the service on a single event loop (as FastAPI does).
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings
from .events import EventStore, to_jsonable
from .graph import build_graph
from .llms import get_llm
from .mcp_tools import load_agent_tools
from .speech import transcribe
from .state import SUB_AGENTS, fresh_run_state

LIVE_ONLY_EVENTS = ("token", "state")


def use_selector_event_loop() -> None:
    """Call before the event loop starts on Windows (psycopg async cannot use the Proactor loop)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def serialize_state(values: dict) -> dict:
    """AgentState -> JSON (messages as {type, content})."""
    return to_jsonable({k: v for k, v in values.items()})


class IsroAgentService:
    """Owns the Postgres pool, checkpointer, event store, MCP tools and the compiled graph."""

    def __init__(self, database_url: str | None = None) -> None:
        self.settings = get_settings()
        self.database_url = database_url or self.settings.database_url
        self.pool: AsyncConnectionPool | None = None
        self.events: EventStore | None = None
        self.graph = None

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        """Open the database pool, create tables, load MCP tools and compile the graph."""
        if sys.platform == "win32" and isinstance(asyncio.get_running_loop(), asyncio.ProactorEventLoop):
            raise RuntimeError("On Windows call use_selector_event_loop() before the event loop starts "
                               "(psycopg async does not support the Proactor loop).")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        get_llm.cache_clear()  # fresh LLM instances per startup
        self.pool = AsyncConnectionPool(self.database_url, min_size=1, max_size=10, open=False,
                                        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        await self.pool.open(wait=True, timeout=30)
        checkpointer = AsyncPostgresSaver(self.pool)
        await checkpointer.setup()                       # LangGraph checkpoint tables
        self.events = EventStore(self.pool)
        await self.events.setup()                        # agent_events table
        agent_tools = await load_agent_tools()           # one tool set per MCP server / sub-agent
        self.graph = build_graph(agent_tools, checkpointer)

    async def shutdown(self) -> None:
        if self.pool:
            await self.pool.close()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

    # ------------------------------------------------------------------ streaming run
    async def stream(self, question: str, thread_id: str, *, run_id: str | None = None, input_type: str = "text",
                     transcript: dict | None = None, include_state: bool = True) -> AsyncIterator[dict]:
        """Run the graph for one user question and yield events as they happen.

        Args:
            question: the user's question (typed or transcribed).
            thread_id: conversation thread (LangGraph checkpoint key, memory + usage persist per thread).
            run_id: id for this run; generated if omitted (the API passes its ``runs.id``).
            input_type: "text" or "voice".
            transcript: speech-to-text result for voice questions.
            include_state: also yield live ``state`` events (full AgentState after each node).
        """
        if self.graph is None:
            raise RuntimeError("call startup() first")
        run_id = run_id or str(uuid.uuid4())
        seq, t0 = 0, time.perf_counter()
        config = self._config(thread_id)

        async def record(event_type: str, node: str | None, payload: dict) -> dict:
            nonlocal seq
            seq += 1
            return await self.events.append(thread_id=thread_id, run_id=run_id, seq=seq, node=node,
                                            event_type=event_type, payload=payload)

        def live(event_type: str, node: str | None, payload: dict) -> dict:
            return {"event_type": event_type, "node": node, "thread_id": thread_id, "run_id": run_id, "seq": seq,
                    "payload": payload}

        yield await record("run_started", None, {"question": question, "input_type": input_type,
                                                 **({"transcript": transcript} if transcript else {})})
        graph_input = {**fresh_run_state(question), "messages": [HumanMessage(question)]}
        agents_used: list[str] = []
        try:
            async for mode, chunk in self.graph.astream(graph_input, config,
                                                        stream_mode=["updates", "custom", "messages"]):
                if mode == "custom":                       # progress events emitted inside nodes
                    ev = dict(chunk)
                    yield await record(ev.pop("event_type"), ev.pop("node", None), ev)
                elif mode == "updates":                    # the AgentState delta each node returned
                    for node, delta in chunk.items():
                        if not delta:
                            continue
                        if node in SUB_AGENTS:
                            agents_used.append(node)
                        yield await record("state_update", node, {"changes": to_jsonable(delta)})
                    if include_state:
                        snapshot = await self.graph.aget_state(config)
                        yield live("state", None, {"agent_state": serialize_state(snapshot.values)})
                elif mode == "messages":                   # answer tokens of the final agent only
                    msg, meta = chunk
                    if meta.get("langgraph_node") == "final_agent" and isinstance(msg, AIMessageChunk) and msg.content:
                        yield live("token", "final_agent", {"text": msg.content})
        except asyncio.CancelledError:
            await record("error", None, {"error": "cancelled"})
            raise
        except Exception as e:  # noqa: BLE001
            yield await record("error", None, {"error": f"{type(e).__name__}: {str(e)[:500]}"})
            raise

        final = (await self.graph.aget_state(config)).values
        yield await record("run_finished", None, {
            "seconds": round(time.perf_counter() - t0, 2), "agents_used": agents_used,
            "answer_chars": len(final.get("final_agent", "")),
            "run_usage": final.get("run_usage", {}), "thread_usage": final.get("thread_usage", {})})

    # ------------------------------------------------------------------ non-streaming helpers
    async def ask(self, question: str, thread_id: str, *, run_id: str | None = None, input_type: str = "text",
                  transcript: dict | None = None) -> dict:
        """Run one question to completion and return the collected result."""
        result = {"thread_id": thread_id, "question": question, "answer": "", "agent_contents": {},
                  "sources": [], "agents_used": [], "router_decisions": [], "seconds": None, "run_id": None,
                  "run_usage": {}, "thread_usage": {}}
        async for ev in self.stream(question, thread_id, run_id=run_id, input_type=input_type,
                                    transcript=transcript, include_state=False):
            et, p = ev["event_type"], ev.get("payload", {})
            result["run_id"] = ev.get("run_id")
            if et == "router_decision":
                result["router_decisions"].append({k: p["structured"][k] for k in ("next_agent", "task", "reason")})
            elif et == "agent_content":
                result["agent_contents"][ev["node"]] = p["content"]
            elif et == "final_answer":
                result["answer"], result["sources"] = p["answer"], p["sources"]
            elif et == "run_finished":
                for k in ("agents_used", "seconds", "run_usage", "thread_usage"):
                    result[k] = p[k]
        if transcript:
            result["transcript"] = transcript
        return result

    async def ask_audio(self, audio: bytes, filename: str, content_type: str, thread_id: str) -> dict:
        tr = await transcribe(audio, filename, content_type)
        if not tr["text"]:
            raise RuntimeError("No speech recognised in the audio")
        return await self.ask(tr["text"], thread_id, input_type="voice", transcript=tr)

    async def stream_audio(self, audio: bytes, filename: str, content_type: str,
                           thread_id: str) -> AsyncIterator[dict]:
        tr = await transcribe(audio, filename, content_type)
        if not tr["text"]:
            raise RuntimeError("No speech recognised in the audio")
        async for ev in self.stream(tr["text"], thread_id, input_type="voice", transcript=tr):
            yield ev

    # ------------------------------------------------------------------ revisiting threads
    async def get_state(self, thread_id: str) -> dict:
        """Current AgentState of a thread ({} if the thread has never run)."""
        snap = await self.graph.aget_state(self._config(thread_id))
        return serialize_state(snap.values) if snap and snap.values else {}

    async def state_history(self, thread_id: str, limit: int = 200) -> list[dict]:
        """AgentState snapshot after every graph step, oldest first."""
        out = []
        async for snap in self.graph.aget_state_history(self._config(thread_id), limit=limit):
            meta = snap.metadata or {}
            out.append({"checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
                        "created_at": snap.created_at, "step": meta.get("step"),
                        "source": meta.get("source"), "next": list(snap.next),
                        "agent_state": serialize_state(snap.values)})
        return list(reversed(out))

    async def history(self, thread_id: str, run_id: str | None = None, after_id: int = 0) -> list[dict]:
        return await self.events.thread_events(thread_id, run_id, after_id)

    async def threads(self, limit: int = 50) -> list[dict]:
        return await self.events.threads(limit)

"""
Append-only event log in PostgreSQL (table agent_events).

Every AgentState change ('state_update', the delta a node returned) and every progress event emitted by
the nodes (router_decision, agent_started, query_rewritten, tool_called, tool_result, agent_content,
final_answer, ...) is stored in order per thread/run, so the frontend can show live updates and replay
any conversation later. Full state snapshots live separately in the LangGraph checkpointer tables.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

SCHEMA = [  # one statement per execute: the pool uses prepared statements (prepare_threshold=0)
"""
CREATE TABLE IF NOT EXISTS agent_events (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT        NOT NULL,
    run_id      UUID        NOT NULL,
    seq         INTEGER     NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    node        TEXT,
    event_type  TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, seq)
)""",
"CREATE INDEX IF NOT EXISTS agent_events_thread_idx ON agent_events (thread_id, id)",
]


def to_jsonable(value: Any) -> Any:
    """LangChain messages and other objects -> JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "type") and hasattr(value, "content"):  # BaseMessage
        return {"type": value.type, "content": value.content}
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class EventStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as conn:
            for statement in SCHEMA:
                await conn.execute(statement)

    async def append(self, *, thread_id: str, run_id: str, seq: int, node: str | None, event_type: str,
                     payload: dict) -> dict:
        row = {"thread_id": thread_id, "run_id": run_id, "seq": seq, "node": node, "event_type": event_type,
               "payload": to_jsonable(payload)}
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO agent_events (thread_id, run_id, seq, node, event_type, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, ts",
                (thread_id, run_id, seq, node, event_type, Jsonb(row["payload"])))
            got = await cur.fetchone()  # the shared pool uses dict rows (required by the checkpointer)
        return {"id": got["id"], "ts": got["ts"].isoformat(), **row}

    async def thread_events(self, thread_id: str, run_id: str | None = None, after_id: int = 0) -> list[dict]:
        """Replay: all events of a thread (optionally one run, or only those after an id for polling)."""
        sql = ("SELECT id, ts, thread_id, run_id::text AS run_id, seq, node, event_type, payload FROM agent_events "
               "WHERE thread_id = %s AND id > %s" + (" AND run_id = %s" if run_id else "") + " ORDER BY id")
        params = (thread_id, after_id, run_id) if run_id else (thread_id, after_id)
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        return [{**r, "ts": r["ts"].isoformat()} for r in rows]

    async def threads(self, limit: int = 50) -> list[dict]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT thread_id, min(ts) AS started, max(ts) AS last_activity, count(DISTINCT run_id) AS runs "
                "FROM agent_events GROUP BY thread_id ORDER BY max(ts) DESC LIMIT %s", (limit,))
            rows = await cur.fetchall()
        return [{**r, "started": r["started"].isoformat(), "last_activity": r["last_activity"].isoformat()}
                for r in rows]

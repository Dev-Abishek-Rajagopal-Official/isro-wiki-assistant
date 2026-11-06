"""
WebSocket fan-out over Redis pub/sub.

Runs publish every message to ``ws:thread:{thread_id}``; user-level notices (e.g. a generated
conversation title) go to ``ws:user:{user_id}``. Each WebSocket connection has one ``Subscription``
that listens to its user channel plus the threads it asked about or subscribed to. Because delivery goes
through Redis, a run executing on one API instance reaches sockets connected to any instance, and a
second browser tab on the same thread sees the run live.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

log = logging.getLogger(__name__)


def thread_channel(thread_id: str) -> str:
    return f"ws:thread:{thread_id}"


def user_channel(user_id: str) -> str:
    return f"ws:user:{user_id}"


class Hub:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish_thread(self, thread_id: str, message: dict) -> None:
        await self.redis.publish(thread_channel(thread_id), json.dumps(message, default=str))

    async def publish_user(self, user_id: str, message: dict) -> None:
        await self.redis.publish(user_channel(user_id), json.dumps(message, default=str))

    def subscription(self, user_id: str, send: Callable[[dict], Awaitable[None]]) -> Subscription:
        return Subscription(self.redis, user_id, send)


class Subscription:
    """One per WebSocket: forwards messages from subscribed channels to the socket."""

    def __init__(self, redis: Redis, user_id: str, send: Callable[[dict], Awaitable[None]]) -> None:
        self.pubsub = redis.pubsub(ignore_subscribe_messages=True)
        self.user_id, self.send = user_id, send
        self.threads: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.pubsub.subscribe(user_channel(self.user_id))
        self._task = asyncio.create_task(self._pump(), name=f"ws-pump-{self.user_id}")

    async def add_thread(self, thread_id: str) -> None:
        if thread_id not in self.threads:
            await self.pubsub.subscribe(thread_channel(thread_id))
            self.threads.add(thread_id)

    async def remove_thread(self, thread_id: str) -> None:
        if thread_id in self.threads:
            await self.pubsub.unsubscribe(thread_channel(thread_id))
            self.threads.discard(thread_id)

    async def _pump(self) -> None:
        while True:
            try:
                msg = await self.pubsub.get_message(timeout=1.0)
                if msg and msg.get("type") == "message":
                    await self.send(json.loads(msg["data"]))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  (socket closed / transient redis error)
                log.exception("ws pump error")
                await asyncio.sleep(0.5)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.pubsub.aclose()

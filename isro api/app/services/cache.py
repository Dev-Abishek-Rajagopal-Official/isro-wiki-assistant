"""Small JSON cache on Redis (users, usage aggregates, health)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis


class Cache:
    def __init__(self, redis: Redis, prefix: str = "cache:") -> None:
        self.redis, self.prefix = redis, prefix

    async def get(self, key: str) -> Any | None:
        raw = await self.redis.get(self.prefix + key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self.redis.set(self.prefix + key, json.dumps(value, default=str), ex=ttl)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self.redis.delete(*(self.prefix + k for k in keys))

    async def get_or_set(self, key: str, ttl: int, producer: Callable[[], Awaitable[Any]]) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await producer()
        await self.set(key, value, ttl)
        return value

    async def delete_pattern(self, pattern: str) -> None:
        async for k in self.redis.scan_iter(self.prefix + pattern):
            await self.redis.delete(k)

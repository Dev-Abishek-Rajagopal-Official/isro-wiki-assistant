"""Redis client factory (async, decoded strings)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings


def create_redis(url: str | None = None) -> Redis:
    return Redis.from_url(url or get_settings().redis_url, decode_responses=True, health_check_interval=30)

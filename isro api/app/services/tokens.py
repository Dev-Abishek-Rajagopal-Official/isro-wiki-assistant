"""
Redis token store.

Keys
    auth:rt:{sha256(refresh)}      -> user_id                 TTL = refresh lifetime   (refresh tokens)
    auth:user_rt:{user_id}         -> set of refresh hashes   (for logout-everywhere)
    auth:revoked:{jti}             -> "1"                     TTL = access token's remaining life
    auth:revoked_before:{user_id}  -> unix ts                 access tokens issued before are invalid

Refresh tokens are opaque random strings; only their SHA-256 is stored. Each use rotates the token
(the old one is deleted atomically), so a stolen refresh token works at most once.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from redis.asyncio import Redis

from app.core.config import get_settings


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.refresh_ttl = get_settings().refresh_token_days * 86400

    async def issue_refresh(self, user_id: str) -> str:
        token = secrets.token_urlsafe(48)
        h = _hash(token)
        async with self.redis.pipeline(transaction=True) as p:
            p.set(f"auth:rt:{h}", user_id, ex=self.refresh_ttl)
            p.sadd(f"auth:user_rt:{user_id}", h)
            p.expire(f"auth:user_rt:{user_id}", self.refresh_ttl)
            await p.execute()
        return token

    async def consume_refresh(self, token: str) -> str | None:
        """Atomically delete a refresh token and return its user id (None if unknown/expired/used)."""
        h = _hash(token)
        user_id = await self.redis.getdel(f"auth:rt:{h}")
        if user_id:
            await self.redis.srem(f"auth:user_rt:{user_id}", h)
        return user_id

    async def revoke_refresh(self, token: str) -> None:
        await self.consume_refresh(token)

    async def revoke_access(self, jti: str, exp: int) -> None:
        ttl = max(1, exp - int(time.time()))
        await self.redis.set(f"auth:revoked:{jti}", "1", ex=ttl)

    async def revoke_all(self, user_id: str) -> None:
        """Logout everywhere: drop all refresh tokens, invalidate access tokens issued until now."""
        hashes = await self.redis.smembers(f"auth:user_rt:{user_id}")
        async with self.redis.pipeline(transaction=True) as p:
            for h in hashes:
                p.delete(f"auth:rt:{h}")
            p.delete(f"auth:user_rt:{user_id}")
            p.set(f"auth:revoked_before:{user_id}", int(time.time()),
                  ex=get_settings().access_token_minutes * 60)
            await p.execute()

    async def is_access_revoked(self, claims: dict) -> bool:
        if await self.redis.exists(f"auth:revoked:{claims['jti']}"):
            return True
        # strict '<' so a login right after logout-everywhere (same second) still works; the token used
        # to call logout-everywhere is revoked by jti as well
        before = await self.redis.get(f"auth:revoked_before:{claims['sub']}")
        return before is not None and claims["iat"] < int(before)

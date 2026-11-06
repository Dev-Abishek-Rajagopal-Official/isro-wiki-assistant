"""
Shared FastAPI dependencies: database session, Redis services, and authentication.

``CurrentUser`` validates the bearer JWT (signature, expiry, revocation in Redis) and loads the user
(cached in Redis). The same logic authenticates WebSocket connections (``authenticate_token``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenError, decode_access_token
from app.db.models import User
from app.services.cache import Cache
from app.services.tokens import TokenStore

bearer = HTTPBearer(auto_error=False, description="JWT access token from /auth/login")


@dataclass
class AuthUser:
    """The authenticated user plus the token claims (needed to revoke the token on logout)."""
    id: uuid.UUID
    email: str
    full_name: str
    claims: dict

    @property
    def is_admin(self) -> bool:
        return get_settings().is_admin_email(self.email)


class AuthError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


def get_tokens(request: Request) -> TokenStore:
    return request.app.state.tokens


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


async def authenticate_token(token: str, *, db, tokens: TokenStore, cache: Cache) -> AuthUser:
    """Validate an access token and return the user. Raises AuthError."""
    try:
        claims = decode_access_token(token)
    except TokenError as e:
        raise AuthError(str(e)) from e
    if await tokens.is_access_revoked(claims):
        raise AuthError("token revoked")

    user_key = f"user:{claims['sub']}"
    cached = await cache.get(user_key)
    if cached is None:
        async with db.sessionmaker() as session:
            user = await session.get(User, uuid.UUID(claims["sub"]))
        if user is None:
            raise AuthError("user not found")
        cached = {"id": str(user.id), "email": user.email, "full_name": user.full_name, "is_active": user.is_active}
        await cache.set(user_key, cached, get_settings().user_cache_ttl_s)
    if not cached["is_active"]:
        raise AuthError("user inactive")
    return AuthUser(id=uuid.UUID(cached["id"]), email=cached["email"], full_name=cached["full_name"], claims=claims)


async def get_current_user(request: Request,
                           creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> AuthUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return await authenticate_token(creds.credentials, db=request.app.state.db,
                                        tokens=request.app.state.tokens, cache=request.app.state.cache)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, e.detail, headers={"WWW-Authenticate": "Bearer"}) from e


async def require_admin(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    """Admins only. Everyone else gets 404, so the admin area is not even revealed."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return user


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
AdminUser = Annotated[AuthUser, Depends(require_admin)]
TokensDep = Annotated[TokenStore, Depends(get_tokens)]
CacheDep = Annotated[Cache, Depends(get_cache)]

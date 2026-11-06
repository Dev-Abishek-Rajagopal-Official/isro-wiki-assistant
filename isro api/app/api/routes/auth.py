"""Authentication: register, login, refresh (rotating), logout, logout everywhere, me."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CacheDep, CurrentUser, SessionDep, TokensDep
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import LoginRequest, MeOut, RefreshRequest, TokenPair, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# verifying against a dummy hash keeps response time the same for unknown emails (no user enumeration)
_DUMMY_HASH = hash_password("dummy-password-1")


async def _token_pair(user_id: uuid.UUID, tokens) -> TokenPair:
    access, _ = create_access_token(user_id)
    refresh = await tokens.issue_refresh(str(user_id))
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=get_settings().access_token_minutes * 60)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, session: SessionDep) -> User:
    """Create a user account (email must be unique). Admin emails are reserved: there is no email
    verification, so they can only be created with scripts/create_admin.py."""
    if get_settings().is_admin_email(body.email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this email is reserved")
    user = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from e
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, session: SessionDep, tokens: TokensDep) -> TokenPair:
    """Exchange email + password for an access token (8 h) and a refresh token (7 days)."""
    user = (await session.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return await _token_pair(user.id, tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: SessionDep, tokens: TokensDep) -> TokenPair:
    """Rotate a refresh token: the old one stops working, a new pair is returned."""
    user_id = await tokens.consume_refresh(body.refresh_token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired refresh token")
    user = await session.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not available")
    return await _token_pair(user.id, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, user: CurrentUser, tokens: TokensDep) -> None:
    """Revoke the current access token and the given refresh token."""
    await tokens.revoke_access(user.claims["jti"], user.claims["exp"])
    await tokens.revoke_refresh(body.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser, tokens: TokensDep, cache: CacheDep) -> None:
    """Logout everywhere: revoke every refresh token and all access tokens issued so far."""
    await tokens.revoke_all(str(user.id))
    await tokens.revoke_access(user.claims["jti"], user.claims["exp"])
    await cache.delete(f"user:{user.id}")


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    """The current user; ``is_admin`` tells the frontend whether to show the admin area."""
    db_user = await session.get(User, user.id)
    if db_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return MeOut.model_validate({**UserOut.model_validate(db_user).model_dump(), "is_admin": user.is_admin})

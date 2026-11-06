"""Password hashing (argon2id) and JWT access tokens."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()


class TokenError(Exception):
    """Raised for any invalid, expired or wrong-type token."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID | str) -> tuple[str, dict]:
    """Return (encoded JWT, claims). Claims carry a unique ``jti`` so the token can be revoked."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "type": "access", "jti": uuid.uuid4().hex,
              "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp())}
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm), claims


def decode_access_token(token: str) -> dict:
    """Validate signature, expiry and type; return the claims."""
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm],
                            options={"require": ["sub", "exp", "iat", "jti"]})
    except jwt.ExpiredSignatureError as e:
        raise TokenError("token expired") from e
    except jwt.PyJWTError as e:
        raise TokenError("invalid token") from e
    if claims.get("type") != "access":
        raise TokenError("wrong token type")
    return claims

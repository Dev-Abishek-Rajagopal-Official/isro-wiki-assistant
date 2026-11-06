"""Auth request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("password must contain letters and digits")
        return v

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("full_name must not be blank")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token lifetime in seconds")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class MeOut(UserOut):
    is_admin: bool = False

"""Usage report models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

GroupBy = Literal["none", "day", "model", "role", "node", "conversation", "thread"]


class TokenCounts(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    avg_llm_call_seconds: float | None = None


class RunStats(BaseModel):
    requests: int = 0                 # agent runs (user questions)
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    voice_requests: int = 0
    error_rate: float = 0.0
    avg_seconds: float | None = None
    p50_seconds: float | None = None
    p95_seconds: float | None = None


class UsageGroup(TokenCounts):
    key: str | None
    label: str | None = None


class RateLimit(BaseModel):
    remaining_requests: int | None = None
    remaining_tokens: int | None = None
    observed_at: datetime | None = None


class UsageReport(BaseModel):
    scope: dict
    period_from: datetime | None
    period_to: datetime | None
    runs: RunStats
    tokens: TokenCounts
    group_by: GroupBy
    groups: list[UsageGroup] = []
    latest_rate_limit: RateLimit | None = None
    source: str = "own tracking: usage reported by Azure AI Foundry on every LLM response"

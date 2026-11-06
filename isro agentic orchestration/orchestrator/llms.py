"""
One LLM instance per role. Every call is timed and turned into an ``llm_call`` record (tokens incl.
reasoning/cached, model, latency, Azure rate-limit headers), which nodes emit as events and add to the
run/thread usage in the agent state.
"""

from __future__ import annotations

import time
from functools import lru_cache

from langchain_openai import ChatOpenAI

from .config import LLM_ROLES, get_settings

RATE_LIMIT_HEADERS = {
    "x-ratelimit-remaining-requests": "ratelimit_remaining_requests",
    "x-ratelimit-remaining-tokens": "ratelimit_remaining_tokens",
}


@lru_cache(maxsize=None)
def get_llm(role: str) -> ChatOpenAI:
    if role not in LLM_ROLES:
        raise ValueError(f"unknown LLM role {role!r}")
    s = get_settings()
    if not (s.llm_base_url and s.llm_api_key):
        raise RuntimeError("Set LLM_BASE_URL and LLM_API_KEY in .env")
    return ChatOpenAI(
        base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.model_for(role),
        timeout=s.llm_timeout_s, max_retries=3,
        tags=[f"llm:{role}"], metadata={"llm_role": role},
        stream_usage=True, include_response_headers=True,
    )


def usage_of(message) -> dict:
    """Token counts reported by the API for one response."""
    u = getattr(message, "usage_metadata", None) or {}
    return {"input_tokens": u.get("input_tokens", 0) or 0, "output_tokens": u.get("output_tokens", 0) or 0,
            "reasoning_tokens": (u.get("output_token_details") or {}).get("reasoning", 0) or 0,
            "cached_tokens": (u.get("input_token_details") or {}).get("cache_read", 0) or 0}


def call_record(role: str, message, seconds: float) -> dict:
    """Everything the API reports about one LLM call, as stored in the llm_calls table."""
    meta = getattr(message, "response_metadata", None) or {}
    headers = {k.lower(): v for k, v in (meta.get("headers") or {}).items()}
    record = {"role": role, "model": meta.get("model_name") or get_settings().model_for(role),
              "seconds": seconds, **usage_of(message)}
    for header, key in RATE_LIMIT_HEADERS.items():
        if header in headers:
            try:
                record[key] = int(headers[header])
            except ValueError:
                pass
    return record


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = round(time.perf_counter() - self.t0, 2)

"""
Settings from the environment, with this package's ``.env`` as fallback.

The ``.env`` file is read into a private mapping, NOT into ``os.environ``: the orchestrator is imported by
other applications (the FastAPI backend), and writing its values (e.g. DATABASE_URL) into the shared process
environment would silently override the host application's own configuration. Real environment variables
still take precedence over the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
_FILE_VALUES = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}


def env(name: str, default: str = "") -> str:
    """Environment variable, else this package's .env value, else ``default``."""
    return os.environ.get(name, _FILE_VALUES.get(name, default))


# Every LLM call in the system has its own role (and so its own model setting + log tag).
LLM_ROLES = [
    "router",
    "rag_rewriter", "rag_generator",
    "launch_rewriter", "launch_generator",
    "wikidata_rewriter", "wikidata_generator",
    "celestrak_rewriter", "celestrak_generator",
    "final",
    "title",          # names conversations from the user's first request (used by the API)
]


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = env("LLM_BASE_URL")
    llm_api_key: str = env("LLM_API_KEY")
    llm_model: str = env("LLM_MODEL", "gpt-6-luna")
    llm_timeout_s: float = float(env("LLM_TIMEOUT_S", "120"))

    speech_endpoint: str = env("SPEECH_ENDPOINT").rstrip("/")
    speech_key: str = env("SPEECH_KEY")
    speech_locales: tuple[str, ...] = tuple(x.strip() for x in env("SPEECH_LOCALES", "en-US").split(",") if x.strip())

    # standalone runs only; the API passes its own database URL to IsroAgentService
    database_url: str = env("DATABASE_URL")

    isromcp_dir: Path = (ROOT / env("ISROMCP_DIR", "../isromcp")).resolve()
    mcp_transport: str = env("MCP_TRANSPORT", "http")
    max_hops: int = int(env("MAX_HOPS", "5"))
    max_tool_result_chars: int = int(env("MAX_TOOL_RESULT_CHARS", "14000"))

    def model_for(self, role: str) -> str:
        """MODEL_<ROLE> overrides the default model for one LLM role (e.g. MODEL_ROUTER)."""
        return env(f"MODEL_{role.upper()}", self.llm_model)


def get_settings() -> Settings:
    return Settings()

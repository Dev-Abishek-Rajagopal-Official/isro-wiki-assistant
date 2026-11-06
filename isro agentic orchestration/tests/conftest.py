"""
Test setup. Live tests use the running docker compose stack (Postgres on :5432, MCP servers on :8101-8104):
when the repo-root .env written by setup.ps1 / setup.sh exists, its Postgres credentials are used with a
separate database (isro_orchestrator, created if missing), so test threads never mix with app data.
An explicit DATABASE_URL in the environment wins.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":  # psycopg async needs the selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DB = "isro_orchestrator"


def _stack_env() -> dict[str, str]:
    path = ROOT.parent / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs if not k.lstrip().startswith("#")}


def _use_stack_database() -> None:
    """Must run before orchestrator.config is imported (its settings read DATABASE_URL at import)."""
    if "DATABASE_URL" in os.environ:
        return
    stack = _stack_env()
    if not stack.get("POSTGRES_PASSWORD"):
        return                                           # no stack: fall back to this package's .env
    user, password = stack.get("POSTGRES_USER") or "isro", stack["POSTGRES_PASSWORD"]
    os.environ["DATABASE_URL"] = f"postgresql://{user}:{password}@localhost:5432/{TEST_DB}"
    try:
        import psycopg
        with psycopg.connect(f"postgresql://{user}:{password}@localhost:5432/postgres", autocommit=True,
                             connect_timeout=3) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
                conn.execute(f"CREATE DATABASE {TEST_DB}")
    except Exception:  # noqa: BLE001 - Postgres not running: live tests skip themselves
        pass


_use_stack_database()

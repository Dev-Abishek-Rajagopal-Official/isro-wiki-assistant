"""
API test setup: a dedicated database (isro_agent_test, migrated with Alembic), Redis DB 15, and the
agent disabled (agent runs are covered by the orchestrator tests and examples/ws_client.py).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DB = "isro_agent_test"


def _root_env() -> dict[str, str]:
    """Postgres / Redis credentials of the running stack: the repo-root .env written by the setup script."""
    path = ROOT.parent / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs if not k.lstrip().startswith("#")}


_stack = _root_env()
PG_USER = os.getenv("TEST_PG_USER") or _stack.get("POSTGRES_USER") or "isro"
PG_PASSWORD = os.getenv("TEST_PG_PASSWORD") or _stack.get("POSTGRES_PASSWORD") or "isro_dev_password"
REDIS_PASSWORD = os.getenv("TEST_REDIS_PASSWORD") or _stack.get("REDIS_PASSWORD") or "isro_redis_dev"
PG_ADMIN_URL = f"postgresql://{PG_USER}:{PG_PASSWORD}@localhost:5432/postgres"

os.environ.update({
    "DATABASE_URL": f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@localhost:5432/{TEST_DB}",
    "REDIS_URL": f"redis://:{REDIS_PASSWORD}@localhost:6379/15",
    "AGENT_ENABLED": "false",
    "ADMIN_EMAILS": "official@abishekrajagopal.com,admin-test@example.com",
})

import psycopg  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis import Redis  # noqa: E402


def _reset_database() -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["database_url"] = os.environ["DATABASE_URL"]
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def test_environment():
    _reset_database()
    Redis.from_url(os.environ["REDIS_URL"]).flushdb()
    yield


@pytest_asyncio.fixture(scope="session")
async def app(test_environment):
    from app.main import create_app

    application = create_app()
    async with LifespanManager(application):
        yield application


@pytest_asyncio.fixture(scope="session")
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def user_factory(client):
    """Create a user and return (headers, tokens, email)."""
    async def make(password: str = "secret-pass-1"):
        email = f"u-{uuid.uuid4().hex[:10]}@example.com"
        r = await client.post("/auth/register", json={"email": email, "full_name": "Test User", "password": password})
        assert r.status_code == 201, r.text
        tokens = (await client.post("/auth/login", json={"email": email, "password": password})).json()
        return {"Authorization": f"Bearer {tokens['access_token']}"}, tokens, email
    return make

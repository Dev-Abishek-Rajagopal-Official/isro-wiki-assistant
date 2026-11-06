"""
FastAPI application factory.

Lifespan: database engine, Redis (token store, caches, pub/sub hub), the LangGraph agent and the run
service are created once and shared through ``app.state``.
Run with ``uv run python run.py`` (sets the Windows selector event loop required by psycopg async).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, conversations, health, threads, usage, ws
from app.core.config import get_settings
from app.core.redis import create_redis
from app.db.session import Database
from app.services.agent import AgentRuntime
from app.services.cache import Cache
from app.services.hub import Hub
from app.services.runs import RunService
from app.services.tokens import TokenStore

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.db = Database(s.database_url)
    app.state.redis = create_redis(s.redis_url)
    await app.state.redis.ping()
    app.state.tokens = TokenStore(app.state.redis)
    app.state.cache = Cache(app.state.redis)
    app.state.hub = Hub(app.state.redis)
    app.state.agent = AgentRuntime(s.agent_database_url, enabled=s.agent_enabled)
    await app.state.agent.start()
    app.state.runs = RunService(db=app.state.db, redis=app.state.redis, hub=app.state.hub, agent=app.state.agent,
                                lock_ttl_s=s.run_lock_ttl_s)
    log.info("startup complete (agent ready=%s)", app.state.agent.ready)
    try:
        yield
    finally:
        for task in list(app.state.runs.active.values()):
            task.cancel()
        await app.state.agent.stop()
        await app.state.redis.aclose()
        await app.state.db.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0", lifespan=lifespan,
                  description="ISRO multi-agent assistant: auth, conversations/threads, WebSocket streaming "
                              "(/ws), history and usage.")
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])
    for module in (auth, conversations, threads, usage, admin, health, ws):
        app.include_router(module.router)
    return app


app = create_app()

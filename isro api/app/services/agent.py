"""Lifecycle wrapper around the orchestrator's IsroAgentService (LangGraph agent)."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from orchestrator.service import IsroAgentService

log = logging.getLogger(__name__)


class AgentRuntime:
    """Starts the agent once per process. If it cannot start (e.g. MCP servers down) the API still runs:
    agent-dependent endpoints answer 503 with the reason, everything else keeps working."""

    def __init__(self, database_url: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.service = IsroAgentService(database_url=database_url)
        self.error: str | None = None if enabled else "agent disabled (AGENT_ENABLED=false)"

    @property
    def ready(self) -> bool:
        return self.enabled and self.error is None and self.service.graph is not None

    async def start(self) -> None:
        if not self.enabled:
            return
        try:
            await self.service.startup()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.error("agent failed to start: %s", self.error)

    async def stop(self) -> None:
        if self.service.pool is not None:
            await self.service.shutdown()

    def require(self) -> IsroAgentService:
        """The agent service, or HTTP 503 if it is not available."""
        if not self.ready:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"agent unavailable: {self.error}")
        return self.service

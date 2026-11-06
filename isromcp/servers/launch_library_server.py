"""
MCP server: Launch Library 2 (The Space Devs) - ISRO launch schedule and history.

Best source for UPCOMING and RECENT launches (fresher than Wikipedia). ISRO = agency id 31.
Anonymous API use is rate-limited (about 15 requests/hour), so responses are cached on disk and the
last good answer is returned (marked stale) if the limit is hit.

Run:  uv run python servers/launch_library_server.py            (stdio)
      uv run python servers/launch_library_server.py --http     (http://127.0.0.1:8102/mcp)
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from common import fetch_json, meta, run_server

BASE = "https://ll.thespacedevs.com/2.3.0"
ISRO_AGENCY_ID = 31
SOURCE = "Launch Library 2 (The Space Devs)"

mcp = FastMCP(
    "isro-launch-library",
    instructions=(
        "Live ISRO launch data from Launch Library 2: upcoming launches, recent launch results, and launch "
        "details. Prefer this over static documents for anything about upcoming or recent launches. "
        "Dates are UTC; 'net' means 'no earlier than' and may change. Check status and net_precision."
    ),
)


def _launch(l: dict) -> dict:
    mission = l.get("mission") or {}
    pad = l.get("pad") or {}
    rocket_cfg = ((l.get("rocket") or {}).get("configuration") or {})
    status = l.get("status") or {}
    precision = l.get("net_precision") or {}
    return {
        "id": l.get("id"),
        "name": l.get("name"),
        "net_utc": l.get("net"),
        "net_precision": precision.get("name"),
        "status": status.get("name"),
        "status_abbrev": status.get("abbrev"),
        "failure_reason": l.get("failreason") or None,
        "provider": (l.get("launch_service_provider") or {}).get("name"),
        "rocket": rocket_cfg.get("full_name") or rocket_cfg.get("name"),
        "mission": mission.get("name"),
        "mission_type": mission.get("type"),
        "mission_description": mission.get("description"),
        "orbit": (mission.get("orbit") or {}).get("name"),
        "pad": pad.get("name"),
        "location": (pad.get("location") or {}).get("name"),
        "webcast_live": l.get("webcast_live"),
        "api_url": l.get("url"),
    }


async def _list(path: str, params: dict, ttl: float) -> dict:
    url = f"{BASE}{path}"
    resp = await fetch_json(url, params={**params, "mode": "normal"}, ttl=ttl, source=SOURCE)
    data = resp["data"]
    return {"count_total": data.get("count"), "launches": [_launch(l) for l in data.get("results", [])],
            **meta(resp, SOURCE, url)}


@mcp.tool
async def upcoming_isro_launches(
    limit: Annotated[int, Field(ge=1, le=20, description="How many upcoming launches")] = 5,
) -> dict:
    """Next scheduled ISRO launches (soonest first): rocket, mission, target date (UTC), status, pad."""
    return await _list("/launches/upcoming/", {"lsp__id": ISRO_AGENCY_ID, "limit": limit, "ordering": "net"},
                       ttl=30 * 60)


@mcp.tool
async def recent_isro_launches(
    limit: Annotated[int, Field(ge=1, le=20, description="How many past launches")] = 5,
) -> dict:
    """Most recent ISRO launches (newest first) with outcome (success / failure / partial failure)."""
    return await _list("/launches/previous/", {"lsp__id": ISRO_AGENCY_ID, "limit": limit, "ordering": "-net"},
                       ttl=6 * 3600)


@mcp.tool
async def search_launches(
    query: Annotated[str, Field(description="Mission, rocket or payload name, e.g. 'Chandrayaan', 'PSLV-C57', 'NISAR'")],
    isro_only: Annotated[bool, Field(description="Only launches where ISRO is the launch provider")] = True,
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict:
    """Search past and future launches by name (newest first)."""
    params = {"search": query, "limit": limit, "ordering": "-net"}
    if isro_only:
        params["lsp__id"] = ISRO_AGENCY_ID
    return await _list("/launches/", params, ttl=6 * 3600)


@mcp.tool
async def launch_details(
    launch_id: Annotated[str, Field(description="Launch id (UUID) from another tool's result")],
) -> dict:
    """Full details of one launch: mission description, orbit, pad, status and failure reason."""
    url = f"{BASE}/launches/{launch_id}/"
    resp = await fetch_json(url, params={"mode": "detailed"}, ttl=6 * 3600, source=SOURCE)
    return {"launch": _launch(resp["data"]), **meta(resp, SOURCE, url)}


if __name__ == "__main__":
    run_server(mcp, default_port=8102)

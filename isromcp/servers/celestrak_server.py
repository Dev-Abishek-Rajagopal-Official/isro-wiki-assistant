"""
MCP server: CelesTrak - satellite catalogue (SATCAT) and current orbital elements.

Use for: "is this satellite still in orbit?", NORAD / international ids, launch date, decay date,
operational status, and the current orbit (apogee, perigee, inclination, period).
Indian objects have owner code 'IND'. Public, no key. SATCAT cached 12 h, orbital elements 2 h
(CelesTrak asks clients not to re-download faster than its update cycle).

Run:  uv run python servers/celestrak_server.py            (stdio)
      uv run python servers/celestrak_server.py --http     (http://127.0.0.1:8104/mcp)
"""

from __future__ import annotations

import math
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from common import fetch_json, meta, run_server

SATCAT = "https://celestrak.org/satcat/records.php"
GP = "https://celestrak.org/NORAD/elements/gp.php"
SOURCE = "CelesTrak"
EARTH_RADIUS_KM = 6378.137
MU_KM3_S2 = 398600.4418

OPS_STATUS = {"+": "operational", "-": "nonoperational", "P": "partially operational", "B": "backup",
              "S": "spare", "X": "extended mission", "D": "decayed", "?": "unknown", "": "unknown"}
OBJECT_TYPE = {"PAY": "payload", "R/B": "rocket body", "DEB": "debris", "UNK": "unknown"}

mcp = FastMCP(
    "isro-celestrak",
    instructions=(
        "Satellite catalogue and live orbital data from CelesTrak. Use it to check whether an Indian satellite "
        "is still in orbit or operational, its NORAD/COSPAR ids, launch and decay dates, and its current orbit. "
        "Search by name first to get the NORAD id."
    ),
)


def _record(r: dict) -> dict:
    return {
        "name": r.get("OBJECT_NAME"),
        "norad_id": r.get("NORAD_CAT_ID"),
        "international_designator": r.get("OBJECT_ID"),
        "object_type": OBJECT_TYPE.get(r.get("OBJECT_TYPE", ""), r.get("OBJECT_TYPE")),
        "owner": r.get("OWNER"),
        "launch_date": r.get("LAUNCH_DATE") or None,
        "launch_site": r.get("LAUNCH_SITE") or None,
        "in_orbit": not r.get("DECAY_DATE"),
        "decay_date": r.get("DECAY_DATE") or None,
        "operational_status": OPS_STATUS.get(r.get("OPS_STATUS_CODE", ""), r.get("OPS_STATUS_CODE")),
        "period_min": r.get("PERIOD"),
        "inclination_deg": r.get("INCLINATION"),
        "apogee_km": r.get("APOGEE"),
        "perigee_km": r.get("PERIGEE"),
    }


@mcp.tool
async def search_satellites(
    name: Annotated[str, Field(description="Full or partial name, e.g. 'CARTOSAT', 'GSAT', 'ASTROSAT', 'IRNSS'")],
    indian_only: Annotated[bool, Field(description="Keep only objects owned by India (owner code IND)")] = True,
    payloads_only: Annotated[bool, Field(description="Skip rocket bodies and debris")] = True,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    """Search the satellite catalogue by name; returns NORAD id, launch/decay dates, status and orbit."""
    resp = await fetch_json(SATCAT, params={"NAME": name.strip(), "FORMAT": "json"}, ttl=12 * 3600, source=SOURCE)
    rows = resp["data"] if isinstance(resp["data"], list) else []
    if indian_only:
        rows = [r for r in rows if r.get("OWNER") == "IND"]
    if payloads_only:
        rows = [r for r in rows if r.get("OBJECT_TYPE") == "PAY"]
    rows.sort(key=lambda r: r.get("LAUNCH_DATE") or "", reverse=True)
    return {"count": len(rows), "satellites": [_record(r) for r in rows[:limit]], **meta(resp, SOURCE, SATCAT)}


@mcp.tool
async def get_satellite(
    norad_id: Annotated[int, Field(ge=1, description="NORAD catalogue number, e.g. 40930 (AstroSat)")],
) -> dict:
    """Catalogue record for one object: identifiers, owner, launch/decay dates, status, orbit summary."""
    resp = await fetch_json(SATCAT, params={"CATNR": norad_id, "FORMAT": "json"}, ttl=12 * 3600, source=SOURCE)
    if not resp["data"]:
        raise ToolError(f"No catalogue record for NORAD id {norad_id}")
    return {"satellite": _record(resp["data"][0]), **meta(resp, SOURCE, SATCAT)}


@mcp.tool
async def get_orbital_elements(
    norad_id: Annotated[int, Field(ge=1, description="NORAD catalogue number")],
) -> dict:
    """Latest orbital elements (GP/OMM) for an object in orbit, with derived apogee/perigee altitude and
    period. Not available for decayed objects."""
    resp = await fetch_json(GP, params={"CATNR": norad_id, "FORMAT": "json"}, ttl=2 * 3600, source=SOURCE)
    data = resp["data"]
    if not isinstance(data, list) or not data:
        raise ToolError(f"No current orbital elements for NORAD id {norad_id} (decayed or unknown)")
    g = data[0]
    n = g["MEAN_MOTION"] * 2 * math.pi / 86400  # rad/s
    a = (MU_KM3_S2 / n ** 2) ** (1 / 3)
    e = g["ECCENTRICITY"]
    return {
        "name": g["OBJECT_NAME"], "norad_id": g["NORAD_CAT_ID"], "international_designator": g["OBJECT_ID"],
        "epoch_utc": g["EPOCH"],
        "inclination_deg": g["INCLINATION"], "eccentricity": e,
        "mean_motion_rev_per_day": g["MEAN_MOTION"],
        "period_min": round(1440 / g["MEAN_MOTION"], 2),
        "apogee_altitude_km": round(a * (1 + e) - EARTH_RADIUS_KM, 1),
        "perigee_altitude_km": round(a * (1 - e) - EARTH_RADIUS_KM, 1),
        "raan_deg": g["RA_OF_ASC_NODE"], "arg_of_perigee_deg": g["ARG_OF_PERICENTER"],
        "mean_anomaly_deg": g["MEAN_ANOMALY"],
        **meta(resp, SOURCE, GP),
    }


if __name__ == "__main__":
    run_server(mcp, default_port=8104)

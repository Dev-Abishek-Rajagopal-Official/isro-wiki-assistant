"""
Live integration tests: every tool of every server is called through a real FastMCP client (in-memory
transport). These hit the real APIs (results are cached on disk, so re-runs are cheap) and the knowledge
base needs Qdrant running.

    uv run pytest -q
"""

import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers"))

import celestrak_server  # noqa: E402
import knowledge_base_server  # noqa: E402
import launch_library_server  # noqa: E402
import wikidata_server  # noqa: E402


async def call(server, tool, args):
    async with Client(server.mcp) as c:
        return (await c.call_tool(tool, args)).data


async def tool_names(server):
    async with Client(server.mcp) as c:
        return {t.name for t in await c.list_tools()}


# ---------------------------------------------------------------- tool listing
@pytest.mark.parametrize("server, expected", [
    (knowledge_base_server, {"search_isro_documents", "get_section_context"}),
    (launch_library_server, {"upcoming_isro_launches", "recent_isro_launches", "search_launches", "launch_details"}),
    (wikidata_server, {"find_wikidata_entity", "get_space_object_facts", "list_isro_missions"}),
    (celestrak_server, {"search_satellites", "get_satellite", "get_orbital_elements"}),
])
async def test_tools_listed(server, expected):
    assert await tool_names(server) == expected


# ---------------------------------------------------------------- knowledge base
async def test_kb_search_returns_cited_facts():
    r = await call(knowledge_base_server, "search_isro_documents", {"query": "Which rocket launched IRNSS-1A?"})
    assert r["relevance"]["likely_in_corpus"] is True
    top = r["results"][0]
    assert "IRNSS-1A" in top["title"] and top["url"].startswith("https://en.wikipedia.org/wiki/")


async def test_kb_out_of_scope_flag():
    r = await call(knowledge_base_server, "search_isro_documents", {"query": "Who won the 2018 FIFA World Cup?"})
    assert r["relevance"]["likely_in_corpus"] is False


async def test_kb_facts_filter_and_parent():
    r = await call(knowledge_base_server, "search_isro_documents",
                   {"query": "GSAT-7 launch mass", "chunk_type": "facts", "top_k": 3})
    assert all(h["chunk_type"] == "facts" for h in r["results"])
    hit = next(h for h in (await call(knowledge_base_server, "search_isro_documents",
                                      {"query": "Chandrayaan-3 mission profile landing", "top_k": 10}))["results"]
               if h["parent_id"])
    sec = await call(knowledge_base_server, "get_section_context", {"parent_id": hit["parent_id"]})
    assert sec["content"] and sec["title"] == hit["title"]


# ---------------------------------------------------------------- launch library
async def test_ll2_upcoming_and_recent():
    up = await call(launch_library_server, "upcoming_isro_launches", {"limit": 3})
    assert up["launches"] and up["source"].startswith("Launch Library")
    rec = await call(launch_library_server, "recent_isro_launches", {"limit": 3})
    assert rec["launches"][0]["status"]
    det = await call(launch_library_server, "launch_details", {"launch_id": rec["launches"][0]["id"]})
    assert det["launch"]["name"] == rec["launches"][0]["name"]


async def test_ll2_search():
    r = await call(launch_library_server, "search_launches", {"query": "Chandrayaan", "limit": 5})
    assert any("Chandrayaan" in (l["name"] or "") or "Chandrayaan" in (l["mission"] or "") for l in r["launches"])


# ---------------------------------------------------------------- wikidata
async def test_wikidata_find_and_facts():
    m = await call(wikidata_server, "find_wikidata_entity", {"name": "Mars Orbiter Mission"})
    assert m["matches"][0]["qid"].startswith("Q")
    f = await call(wikidata_server, "get_space_object_facts", {"entity": "Mars Orbiter Mission"})
    assert f["facts"] and f["qid"].startswith("Q")
    joined = " ".join(" ".join(v) for v in f["facts"].values())
    assert "2013" in joined  # launched 5 Nov 2013


async def test_wikidata_list_missions_filters():
    r = await call(wikidata_server, "list_isro_missions", {"name_contains": "Chandrayaan"})
    assert r["count"] >= 2 and all("chandrayaan" in m["name"].lower() for m in r["missions"])
    with pytest.raises(ToolError):
        await call(wikidata_server, "list_isro_missions", {"launched_from": "2020/01/01"})


# ---------------------------------------------------------------- celestrak
async def test_celestrak_search_record_and_orbit():
    s = await call(celestrak_server, "search_satellites", {"name": "ASTROSAT"})
    sat = next(x for x in s["satellites"] if x["norad_id"] == 40930)
    assert sat["owner"] == "IND" and sat["launch_date"] == "2015-09-28"
    rec = await call(celestrak_server, "get_satellite", {"norad_id": 40930})
    assert rec["satellite"]["name"] == "ASTROSAT"
    orb = await call(celestrak_server, "get_orbital_elements", {"norad_id": 40930})
    assert 550 < orb["perigee_altitude_km"] < 700 and 90 < orb["period_min"] < 100

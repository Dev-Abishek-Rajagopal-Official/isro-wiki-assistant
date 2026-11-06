"""
MCP server: Wikidata - structured facts about ISRO missions, satellites and rockets.

Use for exact, structured values (launch dates, mass, operator, launch vehicle, COSPAR/NORAD ids) and
for lists ("all ISRO missions launched since 2020"). ISRO = Q229058.
Queries the public Wikidata API and SPARQL endpoint (no key). Results cached for 24 h.

Run:  uv run python servers/wikidata_server.py            (stdio)
      uv run python servers/wikidata_server.py --http     (http://127.0.0.1:8103/mcp)
"""

from __future__ import annotations

import re
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from common import fetch_json, meta, run_server

SPARQL = "https://query.wikidata.org/sparql"
ISRO_QID = "Q229058"
SOURCE = "Wikidata (CC0)"
TTL = 24 * 3600

# Item / date / identifier properties (values via wdt:, labelled by Wikidata itself).
FACT_PROPS = ["P31", "P137", "P176", "P375", "P619", "P620", "P621", "P582", "P448", "P361", "P247", "P377",
              "P2632"]
# Quantity properties (value + unit), e.g. mass, orbit.
QUANTITY_PROPS = ["P2067", "P2243", "P2244", "P2045", "P2146"]

mcp = FastMCP(
    "isro-wikidata",
    instructions=(
        "Structured facts from Wikidata about ISRO spacecraft, missions and rockets: launch dates, mass, "
        "operator, manufacturer, launch vehicle, launch site, COSPAR and NORAD ids, orbital parameters, and "
        "lists of ISRO-operated missions. Values are community-maintained; cite the Wikidata url."
    ),
)


def _clean(text: str) -> str:
    """Make user text safe inside a SPARQL string literal."""
    return re.sub(r"[\"\\\n\r{}<>]", " ", text).strip().lower()


async def _sparql(query: str) -> dict:
    return await fetch_json(SPARQL, params={"query": query}, ttl=TTL, source="Wikidata SPARQL",
                            headers={"Accept": "application/sparql-results+json"})


async def _search(name: str, limit: int) -> tuple[list[dict], dict]:
    """Entity search via SPARQL's mwapi service. (The action API wbsearchentities returns 403 unless the
    User-Agent carries personal contact details; the SPARQL endpoint does not require them.)"""
    q = f"""
    SELECT ?item ?itemLabel ?itemDescription ?num WHERE {{
      SERVICE wikibase:mwapi {{
        bd:serviceParam wikibase:endpoint "www.wikidata.org" ; wikibase:api "EntitySearch" ;
                        mwapi:search "{_clean(name)}" ; mwapi:language "en" .
        ?item wikibase:apiOutputItem mwapi:item .
        ?num wikibase:apiOrdinal true .
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} ORDER BY ?num LIMIT {int(limit)}"""
    resp = await _sparql(q)
    items = [{"qid": b["item"]["value"].rsplit("/", 1)[-1], "label": b.get("itemLabel", {}).get("value"),
              "description": b.get("itemDescription", {}).get("value")}
             for b in resp["data"]["results"]["bindings"]]
    return items, resp


@mcp.tool
async def find_wikidata_entity(
    name: Annotated[str, Field(description="Name to look up, e.g. 'Chandrayaan-3', 'PSLV', 'Aditya-L1'")],
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict:
    """Find Wikidata items (Q-ids) matching a name, with their short descriptions."""
    items, resp = await _search(name, limit)
    for it in items:
        it["url"] = f"https://www.wikidata.org/wiki/{it['qid']}"
    return {"matches": items, **meta(resp, SOURCE, SPARQL)}


@mcp.tool
async def get_space_object_facts(
    entity: Annotated[str, Field(description="A Q-id (e.g. 'Q20021213') or a name (e.g. 'Mars Orbiter Mission')")],
) -> dict:
    """Structured facts for one spacecraft / mission / rocket: type, operator, manufacturer, launch vehicle,
    launch date and site, end/landing/decay dates, COSPAR and NORAD ids, mass and orbit (with units)."""
    qid = entity.strip()
    resolved_from = None
    if not re.fullmatch(r"Q\d+", qid):
        found, _ = await _search(entity, 1)
        if not found:
            raise ToolError(f"No Wikidata item found for {entity!r}")
        qid, resolved_from = found[0]["qid"], entity

    values = " ".join(f"wdt:{p}" for p in FACT_PROPS)
    facts_q = f"""
    SELECT ?propLabel ?value ?valueLabel WHERE {{
      VALUES ?wdt {{ {values} }}
      wd:{qid} ?wdt ?value .
      ?prop wikibase:directClaim ?wdt .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    qvalues = " ".join(f"(p:{p} psv:{p})" for p in QUANTITY_PROPS)
    qty_q = f"""
    SELECT ?propLabel ?amount ?unitLabel WHERE {{
      VALUES (?p ?psv) {{ {qvalues} }}
      wd:{qid} ?p ?st . ?st ?psv ?node .
      ?node wikibase:quantityAmount ?amount ; wikibase:quantityUnit ?unit .
      ?prop wikibase:claim ?p .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    label_q = f"""
    SELECT ?label ?description ?article WHERE {{
      OPTIONAL {{ wd:{qid} rdfs:label ?label . FILTER(lang(?label) = "en") }}
      OPTIONAL {{ wd:{qid} schema:description ?description . FILTER(lang(?description) = "en") }}
      OPTIONAL {{ ?article schema:about wd:{qid} ; schema:isPartOf <https://en.wikipedia.org/> . }}
    }}"""
    facts_r, qty_r, label_r = await _sparql(facts_q), await _sparql(qty_q), await _sparql(label_q)

    facts: dict[str, list[str]] = {}
    for b in facts_r["data"]["results"]["bindings"]:
        v = b.get("valueLabel", b["value"])["value"]
        if b["value"].get("datatype", "").endswith("dateTime"):
            v = v[:10]
        facts.setdefault(b["propLabel"]["value"], [])
        if v not in facts[b["propLabel"]["value"]]:
            facts[b["propLabel"]["value"]].append(v)
    for b in qty_r["data"]["results"]["bindings"]:
        unit = b["unitLabel"]["value"]
        unit = "" if unit == "1" else f" {unit}"
        facts.setdefault(b["propLabel"]["value"], []).append(f"{b['amount']['value']}{unit}")

    lab = (label_r["data"]["results"]["bindings"] or [{}])[0]
    return {
        "qid": qid,
        "resolved_from_name": resolved_from,
        "label": lab.get("label", {}).get("value"),
        "description": lab.get("description", {}).get("value"),
        "wikipedia_url": lab.get("article", {}).get("value"),
        "facts": facts,
        **meta(facts_r, SOURCE, f"https://www.wikidata.org/wiki/{qid}"),
    }


@mcp.tool
async def list_isro_missions(
    name_contains: Annotated[str | None, Field(description="Optional name filter, e.g. 'Chandrayaan', 'GSAT', 'EOS'")] = None,
    launched_from: Annotated[str | None, Field(description="Optional earliest launch date, YYYY-MM-DD")] = None,
    launched_to: Annotated[str | None, Field(description="Optional latest launch date, YYYY-MM-DD")] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict:
    """List items operated by ISRO on Wikidata (satellites, probes, missions) with launch date and type,
    newest first. Items without a launch date (e.g. unscheduled) are included only without date filters."""
    filters = []
    if name_contains:
        filters.append(f'FILTER(CONTAINS(LCASE(?label), "{_clean(name_contains)}"))')
    for bound, op in ((launched_from, ">="), (launched_to, "<=")):
        if bound:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", bound):
                raise ToolError("Dates must be YYYY-MM-DD")
            filters.append(f'FILTER(BOUND(?launch) && ?launch {op} "{bound}T00:00:00Z"^^xsd:dateTime)')
    q = f"""
    SELECT ?item ?label (SAMPLE(?launch) AS ?launch_date) (GROUP_CONCAT(DISTINCT ?typeLabel; separator=", ") AS ?types)
    WHERE {{
      ?item wdt:P137 wd:{ISRO_QID} ; rdfs:label ?label . FILTER(lang(?label) = "en")
      OPTIONAL {{ ?item wdt:P619 ?launch }}
      OPTIONAL {{ ?item wdt:P31 ?type . ?type rdfs:label ?typeLabel . FILTER(lang(?typeLabel) = "en") }}
      {' '.join(filters)}
    }}
    GROUP BY ?item ?label
    ORDER BY DESC(?launch_date)
    LIMIT {limit}"""
    resp = await _sparql(q)
    rows = [{"qid": b["item"]["value"].rsplit("/", 1)[-1], "name": b["label"]["value"],
             "launch_date": b.get("launch_date", {}).get("value", "")[:10] or None,
             "types": b.get("types", {}).get("value") or None}
            for b in resp["data"]["results"]["bindings"]]
    return {"count": len(rows), "missions": rows, **meta(resp, SOURCE, SPARQL)}


if __name__ == "__main__":
    run_server(mcp, default_port=8103)

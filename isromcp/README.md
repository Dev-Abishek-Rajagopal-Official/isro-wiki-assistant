# isromcp – one FastMCP server per ISRO data source

| Server (file) | Tools | Source | Transport (default) |
|---|---|---|---|
| `isro_knowledge_base` (`servers/knowledge_base_server.py`) | `search_isro_documents`, `get_section_context` | Our RAG: 468 Wikipedia articles in Qdrant (hybrid dense + BM25, config chosen by `isro rag/rag_evals`) | HTTP :8101 |
| `launch_library` (`servers/launch_library_server.py`) | `upcoming_isro_launches`, `recent_isro_launches`, `search_launches`, `launch_details` | Launch Library 2 (The Space Devs), ISRO = agency 31 | stdio |
| `wikidata` (`servers/wikidata_server.py`) | `find_wikidata_entity`, `get_space_object_facts`, `list_isro_missions` | Wikidata SPARQL, ISRO = Q229058 | stdio |
| `celestrak` (`servers/celestrak_server.py`) | `search_satellites`, `get_satellite`, `get_orbital_elements` | CelesTrak SATCAT + GP elements | stdio |

Not included on purpose: the community ISRO API (isro.vercel.app) – unofficial, data ends ~2021, names
only; its centre and customer-satellite lists are covered by the knowledge base and Launch Library.

Every tool returns provenance (`source`, `source_url`, `fetched_at`, `from_cache`) so the agent can cite it.
Web responses are cached in `.cache/http_cache.sqlite` (TTL per tool); if an API fails or rate-limits,
the last good answer is returned with a `warning`.

## Setup

```
uv sync
copy .env.example .env        # set MCP_CONTACT (URL or email) - Wikidata returns 403 without it
```
The knowledge base also needs Qdrant running (`docker compose up -d` in `isro rag`) and `isro rag/.env`.

## Use from LangChain (langchain-mcp-adapters)

```
uv run python servers/knowledge_base_server.py --http      # keep running (RAG server)
```
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp_config import connections

client = MultiServerMCPClient(connections())   # KB over HTTP, the other three start over stdio
tools = await client.get_tools()               # 12 LangChain tools -> bind to the LLM / agent
```
Demo: `uv run python examples/langchain_tools_demo.py` (loads all tools, calls one per server).

Why the knowledge base uses HTTP: on Windows, spawned over stdio, its synchronous Qdrant/Azure clients
hung; the same server works over HTTP (and in-process). A long-lived HTTP service also keeps its models
and clients loaded between calls. `connections("http")` switches every server to HTTP
(run each with `--http`; ports 8101-8104).

## Versions

FastMCP 3.x + MCP SDK 1.x on purpose: `langchain-mcp-adapters` (0.3.x) requires `mcp<2`, while FastMCP 4
needs MCP SDK 2.x. Same protocol version on both sides.

## Tests

`uv run pytest -q` – live tests calling every tool through a real FastMCP client (needs network and
Qdrant; Wikidata tests need `MCP_CONTACT`).

## Notes on sources

- Launch Library 2 anonymous access is rate-limited (~15 requests/hour); caching keeps usage low.
- CelesTrak: search by name / NORAD id; owner filtering is done client-side (`IND`).

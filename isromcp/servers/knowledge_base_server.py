"""
MCP server: ISRO knowledge base (RAG over 468 cleaned English-Wikipedia articles in Qdrant).

Retrieval = the configuration chosen by the evaluation in isro rag/rag_evals (see REPORT.md):
structure-aware ~350-token chunks with breadcrumb, Azure text-embedding-3-large (dense) + BM25 (sparse),
Reciprocal Rank Fusion in Qdrant, top 5, no reranker. The isro rag code is imported, not copied.

Requires: Qdrant running (isro rag: `docker compose up -d`) and isro rag/.env filled in.
Run:  uv run python servers/knowledge_base_server.py            (stdio)
      uv run python servers/knowledge_base_server.py --http     (http://127.0.0.1:8101/mcp)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from common import run_server

RAG_DIR = Path(__file__).resolve().parents[2] / "isro rag"
sys.path.insert(0, str(RAG_DIR))

# Evaluation: real questions' best dense score was >= 0.51, out-of-scope questions <= 0.50.
OUT_OF_SCOPE_THRESHOLD = 0.5
PREFETCH = 30

mcp = FastMCP(
    "isro-knowledge-base",
    instructions=(
        "Search a curated knowledge base of English-Wikipedia articles about ISRO and the Indian space "
        "programme (missions, satellites, launch vehicles, people, facilities, history). Use it for "
        "explanations and facts, and cite the returned title, section and url. If likely_in_corpus is "
        "false, say the documents do not cover the question instead of guessing."
    ),
)

_state: dict = {}
_init_lock = threading.Lock()
log = logging.getLogger("isro-knowledge-base")  # stderr only: stdout carries the MCP protocol
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


def _stack():
    """Load clients and embedders once (first call), not at import time."""
    with _init_lock:
        if not _state:
            log.info("loading retrieval stack ...")
            from config import get_settings
            from embeddings import BM25Embedder, build_dense_embedder
            from index import get_client

            log.info("imports done")
            t = time.time()
            s = get_settings()
            client = get_client(s)
            log.info("qdrant client ready (%.1fs)", time.time() - t)
            dense = build_dense_embedder(s)
            log.info("dense embedder ready (%.1fs)", time.time() - t)
            sparse = BM25Embedder(s.sparse_model, s.model_cache)
            log.info("bm25 ready (%.1fs)", time.time() - t)
            _state.update(settings=s, client=client, dense=dense, sparse=sparse)
    return _state


def _hit(point) -> dict:
    p = point.payload
    return {
        "title": p["title"],
        "section": " > ".join(p["section_path"]),
        "chunk_type": p["chunk_type"],
        "content": p["content"],
        "url": p["url"],
        "revision_id": p.get("revid"),
        "chunk_id": p["chunk_id"],
        "parent_id": p.get("parent_id"),
        "score": round(point.score, 4),
    }


@mcp.tool
async def search_isro_documents(
    query: Annotated[str, Field(description="Natural-language question or keywords, e.g. 'launch mass of GSAT-7'")],
    top_k: Annotated[int, Field(ge=1, le=10, description="Number of passages to return")] = 5,
    chunk_type: Annotated[Literal["text", "facts", "table"] | None,
                          Field(description="Optional filter: 'facts' = infobox key facts, 'table' = tables, "
                                            "'text' = prose")] = None,
) -> dict:
    """Hybrid (semantic + keyword) search over the ISRO Wikipedia knowledge base.

    Returns the best-matching passages with article title, section, Wikipedia url and revision id for
    citation, plus a relevance check: if likely_in_corpus is false the knowledge base probably does not
    cover the question."""
    # The retrieval stack (Qdrant client, Azure client) is synchronous. Run it in a worker thread:
    # blocking network calls made directly in the tool froze the stdio transport on Windows.
    return await asyncio.to_thread(_search, query, top_k, chunk_type)


def _search(query: str, top_k: int, chunk_type: str | None) -> dict:
    from qdrant_client import models

    st = _stack()
    s, client = st["settings"], st["client"]
    from index import DENSE, SPARSE

    flt = None
    if chunk_type:
        flt = models.Filter(must=[models.FieldCondition(key="chunk_type", match=models.MatchValue(value=chunk_type))])
    try:
        t = time.time()
        qv = st["dense"].embed_documents([query])[0]  # cached query embedding
        log.info("query embedded (%.1fs)", time.time() - t)
        sv = st["sparse"].embed_query(query)
        log.info("bm25 query vector (%.1fs)", time.time() - t)
        fused = client.query_points(
            s.chunks_collection,
            prefetch=[models.Prefetch(query=qv, using=DENSE, limit=PREFETCH, filter=flt),
                      models.Prefetch(query=sv, using=SPARSE, limit=PREFETCH, filter=flt)],
            query=models.FusionQuery(fusion=models.Fusion.RRF), limit=top_k, with_payload=True).points
        best = client.query_points(s.chunks_collection, query=qv, using=DENSE, limit=1, query_filter=flt).points
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Knowledge base unavailable ({type(e).__name__}). Is Qdrant running "
                        f"(`docker compose up -d` in isro rag)?") from e

    best_dense = round(best[0].score, 4) if best else 0.0
    return {
        "query": query,
        "results": [_hit(p) for p in fused],
        "relevance": {
            "best_dense_score": best_dense,
            "likely_in_corpus": best_dense >= OUT_OF_SCOPE_THRESHOLD,
            "note": "Scores below ~0.5 indicated out-of-scope questions in evaluation.",
        },
        "source": "English Wikipedia (CC BY-SA 4.0), snapshot indexed in Qdrant",
    }


@mcp.tool
async def get_section_context(
    parent_id: Annotated[str, Field(description="parent_id from a search result, e.g. '35386311:p2'")],
) -> dict:
    """Fetch the full section a search result came from, when a passage alone lacks context.

    Only results with a non-null parent_id have a stored section (very large sections are not stored)."""
    return await asyncio.to_thread(_section, parent_id)


def _section(parent_id: str) -> dict:
    st = _stack()
    from index import point_id

    try:
        got = st["client"].retrieve(st["settings"].parents_collection, [point_id(parent_id)])
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Knowledge base unavailable ({type(e).__name__}). Is Qdrant running?") from e
    if not got:
        raise ToolError(f"No section stored for parent_id {parent_id!r}")
    p = got[0].payload
    return {"title": p["title"], "section": " > ".join(p["section_path"]) or "Whole article",
            "content": p["content"], "url": p["url"], "token_count": p["token_count"]}


if __name__ == "__main__":
    run_server(mcp, default_port=8101)

"""
Retrieval A/B test: every chunking variant x every retrieval pipeline, no LLM involved.

Pipelines
  dense            Azure text-embedding-3-large only
  bm25             sparse keyword search only
  hybrid           dense + bm25, Reciprocal Rank Fusion
  hybrid+<rr>      hybrid top-30 re-scored by a local cross-encoder reranker
  ... +parent      final top-5 expanded to parent sections (context budget check)

Metric = evidence recall@k: is the verbatim evidence sentence of the question inside one of the top-k
chunks? This is independent of how a variant chunks the text, so variants are comparable.
Also: MRR@10, doc_hit@5 (right article in top 5), context tokens, latency.

Every (variant, pipeline) result is appended to results/experiments.csv + experiments.log as soon
as it is computed; per-question rows go to results/details/.

Usage:
    uv run python rag_evals/retrieval_ab.py
    uv run python rag_evals/retrieval_ab.py --variants struct_350 fixed_400 --rerankers minilm
"""

from __future__ import annotations

import argparse
import statistics
import time

from common import EVAL_SET, contains_evidence, log, read_jsonl, record, write_details
from variants import VARIANTS

from qdrant_client import models  # noqa: E402

from config import get_settings  # noqa: E402
from embeddings import BM25Embedder, build_dense_embedder  # noqa: E402
from index import DENSE, SPARSE, get_client, point_id  # noqa: E402

RERANKERS = {
    "minilm": "Xenova/ms-marco-MiniLM-L-12-v2",
    "bge-m3": "BAAI/bge-reranker-v2-m3-int8",
}
PREFETCH = 30            # candidates per method before RRF fusion
RERANK_CANDIDATES = 20   # fused candidates re-scored by the cross-encoder
RERANK_MAX_CHARS = 1200  # ~300 tokens per candidate: CPU cross-encoders are slow (measured 10-100 s/query at 30x full)
FINAL_K = 5


class Retriever:
    def __init__(self, client, dense, sparse, rerankers: dict) -> None:
        self.client, self.dense, self.sparse, self.rerankers = client, dense, sparse, rerankers
        self._qvec: dict[str, list[float]] = {}
        self._svec: dict[str, models.SparseVector] = {}

    def qvec(self, q: str):
        if q not in self._qvec:  # CachedEmbedder.embed_documents -> persistent cache for queries too
            self._qvec[q] = self.dense.embed_documents([q])[0]
        return self._qvec[q]

    def svec(self, q: str):
        if q not in self._svec:
            self._svec[q] = self.sparse.embed_query(q)
        return self._svec[q]

    def search(self, coll: str, q: str, mode: str, k: int) -> list[dict]:
        if mode == "dense":
            pts = self.client.query_points(coll, query=self.qvec(q), using=DENSE, limit=k, with_payload=True).points
        elif mode == "bm25":
            pts = self.client.query_points(coll, query=self.svec(q), using=SPARSE, limit=k, with_payload=True).points
        else:
            pts = self.client.query_points(
                coll,
                prefetch=[models.Prefetch(query=self.qvec(q), using=DENSE, limit=PREFETCH),
                          models.Prefetch(query=self.svec(q), using=SPARSE, limit=PREFETCH)],
                query=models.FusionQuery(fusion=models.Fusion.RRF), limit=k, with_payload=True).points
        return [p.payload for p in pts]

    def rerank(self, name: str, q: str, hits: list[dict], k: int) -> list[dict]:
        docs = [f"{h['breadcrumb']}\n{h['content']}"[:RERANK_MAX_CHARS] for h in hits]
        scores = list(self.rerankers[name].rerank(q, docs))
        order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)
        return [hits[i] for i in order[:k]]

    def expand_parents(self, parents_coll: str, hits: list[dict]) -> list[str]:
        """Replace children by their parent section (deduplicated); others stay as they are."""
        out, seen = [], set()
        for h in hits:
            pid = h.get("parent_id")
            if pid:
                if pid in seen:
                    continue
                seen.add(pid)
                got = self.client.retrieve(parents_coll, [point_id(pid)])
                if got:
                    out.append(got[0].payload["content"])
                    continue
            out.append(h["content"])
        return out


def evaluate(items: list[dict], run) -> tuple[dict, list[dict]]:
    """run(question) -> (ranked chunk payloads (<=10), contexts used as final context, latency_ms)."""
    details, lat = [], []
    for it in items:
        ranked, final_ctx, ms = run(it["question"])
        lat.append(ms)
        ev_rank = next((i + 1 for i, h in enumerate(ranked) if contains_evidence(h["content"], it["evidence"])), None)
        doc_rank = next((i + 1 for i, h in enumerate(ranked) if h["title"] == it["source_title"]), None)
        details.append({
            "id": it["id"], "type": it["type"], "question": it["question"], "source": it["source_title"],
            "evidence_rank": ev_rank, "doc_rank": doc_rank,
            "evidence_in_final_context": any(contains_evidence(c, it["evidence"]) for c in final_ctx),
            "context_tokens": sum(len(c) // 4 for c in final_ctx),
            "top3": [h["breadcrumb"] for h in ranked[:3]],
        })
    n = len(details)

    def at(k):
        return sum(1 for d in details if d["evidence_rank"] and d["evidence_rank"] <= k) / n

    metrics = {
        "evidence_recall@1": at(1), "evidence_recall@3": at(3),
        "evidence_recall@5": sum(d["evidence_in_final_context"] for d in details) / n,
        "evidence_recall@10": at(10),
        "mrr@10": sum(1 / d["evidence_rank"] for d in details if d["evidence_rank"]) / n,
        "doc_hit@5": sum(1 for d in details if d["doc_rank"] and d["doc_rank"] <= 5) / n,
        "avg_context_tokens": statistics.mean(d["context_tokens"] for d in details),
        "avg_latency_ms": statistics.mean(lat),
        "n_questions": n,
    }
    by_type = {}
    for t in sorted({d["type"] for d in details}):
        sub = [d for d in details if d["type"] == t]
        by_type[t] = round(sum(d["evidence_in_final_context"] for d in sub) / len(sub), 2)
    return metrics, details, by_type


def already_done() -> dict[str, dict]:
    """Retrieval rows already in experiments.csv (label -> row), so a stopped run can resume."""
    import csv

    from common import EXPERIMENTS_CSV

    if not EXPERIMENTS_CSV.exists():
        return {}
    with open(EXPERIMENTS_CSV, encoding="utf-8-sig") as f:
        return {row["variant"]: row for row in csv.DictReader(f) if row["stage"] == "retrieval"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--rerankers", nargs="*", default=list(RERANKERS))
    ap.add_argument("--top-variants", type=int, default=2, help="phase B: rerank only the N best variants")
    ap.add_argument("--slow-reranker-variants", type=int, default=1,
                    help="the slow bge-m3 reranker runs only on the N best variants")
    ap.add_argument("--no-parent", action="store_true", help="skip the parent-expansion runs")
    args = ap.parse_args()
    rank_cache: dict = {}

    s = get_settings()
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    rerankers = {n: TextCrossEncoder(RERANKERS[n], cache_dir=str(s.model_cache)) for n in args.rerankers}
    r = Retriever(get_client(s), build_dense_embedder(s), BM25Embedder(s.sparse_model, s.model_cache), rerankers)
    items = [i for i in read_jsonl(EVAL_SET) if i["in_scope"]]
    oos = [i for i in read_jsonl(EVAL_SET) if not i["in_scope"]]
    log(f"[retrieval] {len(items)} in-scope questions, variants={args.variants}, rerankers={args.rerankers}")

    done = already_done()
    hybrid_scores: dict[str, tuple] = {}

    def run_pipeline(vname: str, mode: str, rr: str | None, parent: bool) -> None:
        v = VARIANTS[vname]
        coll, pcoll = v.chunks_collection, v.parents_collection
        label = f"{vname} | {mode}" + (f"+rerank:{rr}" if rr else "") + ("+parent" if parent else "")
        if label in done:
            log(f"[retrieval] skip {label} (already in experiments.csv)")
            return
        n_chunks = r.client.count(coll).count

        def run(q):
            t0 = time.time()
            key = (vname, mode, rr, q)
            if key not in rank_cache:  # +parent reuses the ranking (and its cost) of the plain run
                ranked = r.search(coll, q, mode, RERANK_CANDIDATES if rr else 10)
                if rr:
                    ranked = r.rerank(rr, q, ranked, 10)
                rank_cache[key] = (ranked, (time.time() - t0) * 1000)
            ranked, rank_ms = rank_cache[key]
            final = ranked[:FINAL_K]
            ctx = r.expand_parents(pcoll, final) if parent else [h["content"] for h in final]
            return ranked, ctx, rank_ms

        if True:
            metrics, details, by_type = evaluate(items, run)
            if mode == "hybrid" and not rr:
                hybrid_scores[vname] = (metrics["evidence_recall@5"], metrics["mrr@10"])
            # out-of-scope: best dense similarity (helps pick a "not in documents" threshold later)
            oos_note = ""
            if mode == "dense" and oos:
                tops = [r.client.query_points(coll, query=r.qvec(o["question"]), using=DENSE, limit=1).points[0].score
                        for o in oos]
                ins = [r.client.query_points(coll, query=r.qvec(i["question"]), using=DENSE, limit=1).points[0].score
                       for i in items]
                oos_note = (f"; top1 dense score in-scope median={statistics.median(ins):.3f} "
                            f"min={min(ins):.3f}, out-of-scope max={max(tops):.3f}")
            record("retrieval", label, {
                **metrics, "chunk_config": vname, "retrieval": mode, "reranker": rr or "",
                "parent_expansion": "yes" if parent else "no", "n_chunks": n_chunks,
            }, notes=f"evidence_recall@5 by type={by_type}{oos_note}")
            write_details(f"retrieval__{label}", details)

    # Phase A: every variant, no reranker (fast).
    for vname in args.variants:
        for mode in ("dense", "bm25", "hybrid"):
            run_pipeline(vname, mode, None, False)
        if vname not in hybrid_scores and f"{vname} | hybrid" in done:
            row = done[f"{vname} | hybrid"]
            hybrid_scores[vname] = (float(row["evidence_recall@5"]), float(row["mrr@10"]))

    # Phase B: rerankers (slow on CPU) only on the best variants by hybrid recall@5, then MRR.
    ranked_variants = sorted(hybrid_scores, key=lambda v: hybrid_scores[v], reverse=True)
    top = ranked_variants[: args.top_variants]
    log(f"[retrieval] phase B: hybrid ranking {[(v, hybrid_scores[v]) for v in ranked_variants]} -> rerank {top}")
    for i, vname in enumerate(top):
        for rr in args.rerankers:
            if rr == "bge-m3" and i >= args.slow_reranker_variants:
                continue
            run_pipeline(vname, "hybrid", rr, False)
            if VARIANTS[vname].kind == "structure" and not args.no_parent:
                run_pipeline(vname, "hybrid", rr, True)


if __name__ == "__main__":
    main()

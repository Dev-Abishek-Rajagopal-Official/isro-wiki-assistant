"""
Build the knowledge base end to end, checking each step before moving on.

  1. verify documents  every row of wiki documents/wiki_metadata.csv has its .md file (with front matter),
                       no stray .md files, and at least --min-docs documents
  2. chunk             chunking.py -> data/chunks.jsonl + data/parents.jsonl
  3. index             index.py -> Qdrant (dense Azure embeddings + BM25). Skipped when Qdrant already holds
                       exactly these chunks (same content hash and point counts) - re-running setup is cheap
  4. verify Qdrant     point counts equal the chunk / parent counts and a hybrid test query returns hits

    python build_knowledge_base.py                   # all steps
    python build_knowledge_base.py --verify-docs     # step 1 only (used right after a wiki download)
    python build_knowledge_base.py --force           # re-index even if nothing changed

Exits non-zero on the first failed check, so setup scripts can stop there.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from chunking import document_paths
from config import get_settings

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / "wiki documents"
META_CSV = "wiki_metadata.csv"
STATE = Path(os.getenv("KB_STATE") or HERE / "data" / "kb_state.json")


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"FAILED: {msg}", flush=True)
    sys.exit(1)


def verify_docs(docs: Path, min_docs: int) -> int:
    step(f"Verify documents in {docs}")
    meta = docs / META_CSV
    if not meta.exists():
        fail(f"{META_CSV} not found - run the wiki download first (WIKI_DOWNLOAD=true)")
    with open(meta, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    listed = {r["file_name"] for r in rows}
    on_disk = {p.name for p in document_paths(docs)}
    missing = sorted(listed - on_disk)
    stray = sorted(on_disk - listed)
    bad = [n for n in sorted(listed & on_disk) if not (docs / n).read_text(encoding="utf-8").startswith("---")]
    if missing:
        fail(f"{len(missing)} documents listed in {META_CSV} are missing, e.g. {missing[:5]}")
    if bad:
        fail(f"{len(bad)} documents have no front matter, e.g. {bad[:5]}")
    if len(listed) < min_docs:
        fail(f"only {len(listed)} documents (expected at least {min_docs})")
    if stray:
        print(f"note: {len(stray)} .md files are not in {META_CSV} and will still be chunked: {stray[:5]}")
    print(f"OK: {len(listed)} documents, all present")
    return len(listed)


def run(script: str) -> None:
    t0 = time.time()
    r = subprocess.run([sys.executable, script], cwd=HERE)
    if r.returncode:
        fail(f"{script} exited with {r.returncode}")
    print(f"({script}: {time.time() - t0:.0f} s)")


def count_lines(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def fingerprint(s, *paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    h.update(f"{s.embed_deployment}|{s.embed_dimensions}|{s.sparse_model}|"
              f"{s.chunks_collection}|{s.parents_collection}".encode())
    return h.hexdigest()


def qdrant_counts(client, s) -> tuple[int, int]:
    def n(name: str) -> int:
        return client.count(name, exact=True).count if client.collection_exists(name) else 0
    return n(s.chunks_collection), n(s.parents_collection)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify-docs", action="store_true", help="only verify the documents")
    ap.add_argument("--force", action="store_true", help="re-index even if Qdrant is up to date")
    ap.add_argument("--min-docs", type=int, default=int(os.getenv("MIN_DOCS", "100")))
    args = ap.parse_args()

    verify_docs(DOCS, args.min_docs)
    if args.verify_docs:
        return

    s = get_settings()
    if not (s.azure_endpoint and s.azure_api_key):
        fail("AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY are not set (needed for the dense embeddings)")

    step("Chunk documents")
    run("chunking.py")
    chunks_path, parents_path = s.data_dir / "chunks.jsonl", s.data_dir / "parents.jsonl"
    n_chunks, n_parents = count_lines(chunks_path), count_lines(parents_path)
    print(f"OK: {n_chunks} chunks, {n_parents} parent sections")

    from index import get_client
    client = get_client(s)
    fp = fingerprint(s, chunks_path, parents_path)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    step(f"Index into Qdrant ({s.qdrant_url or 'local mode'})")
    if not args.force and state.get("fingerprint") == fp and qdrant_counts(client, s) == (n_chunks, n_parents):
        print("up to date - same chunks already indexed, skipping (use --force to rebuild)")
    else:
        run("index.py")

    step("Verify Qdrant")
    got = qdrant_counts(client, s)
    if got != (n_chunks, n_parents):
        fail(f"Qdrant holds {got[0]} chunks / {got[1]} parents, expected {n_chunks} / {n_parents}")
    from embeddings import BM25Embedder, build_dense_embedder
    from search import hybrid_search
    hits = hybrid_search(client, s.chunks_collection, build_dense_embedder(s), BM25Embedder(s.sparse_model, s.model_cache),
                         "Which rocket launched Chandrayaan-3?", k=3)
    if not hits:
        fail("test query returned no results")
    print(f"OK: {got[0]} chunks + {got[1]} parents indexed; test query top hit: {hits[0].payload.get('breadcrumb')}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"fingerprint": fp, "chunks": n_chunks, "parents": n_parents,
                                 "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2))
    print("\nKnowledge base ready.")


if __name__ == "__main__":
    main()

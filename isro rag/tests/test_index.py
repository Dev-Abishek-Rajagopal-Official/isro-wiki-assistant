"""Indexing + hybrid search against in-memory Qdrant. A fake dense embedder replaces Azure OpenAI,
so these tests need no API keys (BM25 runs locally via fastembed)."""

import hashlib
import json
import math
import re
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chunking import chunk_document  # noqa: E402
from embeddings import BM25Embedder, CachedEmbedder  # noqa: E402
from index import build_index, point_id  # noqa: E402
from search import hybrid_search  # noqa: E402


class FakeDense:
    """Hashed bag-of-words, L2-normalised: deterministic and good enough to rank by word overlap."""
    model_id = "fake:64"

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * 64
        for w in re.findall(r"[a-z0-9\-]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]

    def embed_documents(self, texts):
        self.calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def make_doc(title: str, pageid: int, facts: str, sections: dict[str, str]) -> str:
    body = "\n\n".join(f"## {h}\n\n{t}" for h, t in sections.items())
    return (f'---\ntitle: "{title}"\nurl: "https://en.wikipedia.org/wiki/{title}"\npageid: {pageid}\n'
            f'revid: 1\n---\n\n# {title}\n\n{title} is an Indian satellite.\n\n## Key facts\n\n{facts}\n\n{body}\n')


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    # ~900 tokens in 6 paragraphs: split into several chunks, but small enough to have a parent
    long = "\n\n".join(" ".join(f"The {p}-{i} orbit raising manoeuvre used the liquid apogee motor."
                                for i in range(10)) for p in range(6))
    docs = [
        make_doc("GSAT-7", 1, "- Launch mass: 2,650 kilograms\n- Rocket: Ariane 5 ECA",
                 {"Mission": "Rukmini serves the Indian Navy with multi-band communication.", "Orbit": long}),
        make_doc("IRNSS-1A", 2, "- Launch mass: 1,425 kilograms\n- Rocket: PSLV-XL C22",
                 {"Partial failure": "Three rubidium atomic clocks failed in 2016."}),
        make_doc("Chandrayaan-3", 3, "- Lander: Vikram\n- Rover: Pragyan",
                 {"Landing": "The Vikram lander touched down near the lunar south pole in August 2023."}),
    ]
    with open(d / "chunks.jsonl", "w", encoding="utf-8") as cf, open(d / "parents.jsonl", "w", encoding="utf-8") as pf:
        for md in docs:
            chunks, parents = chunk_document(md)
            cf.writelines(json.dumps(asdict(c)) + "\n" for c in chunks)
            pf.writelines(json.dumps(asdict(p)) + "\n" for p in parents)
    return d


@pytest.fixture(scope="module")
def index(corpus):
    client = QdrantClient(":memory:")
    dense, sparse = FakeDense(), BM25Embedder()
    counts = build_index(client, dense, sparse, corpus / "chunks.jsonl", corpus / "parents.jsonl",
                         "chunks", "parents", batch_size=4)
    return client, dense, sparse, counts


def test_all_chunks_and_parents_indexed(index, corpus):
    client, _, _, counts = index
    n_lines = sum(1 for _ in open(corpus / "chunks.jsonl", encoding="utf-8"))
    assert counts["chunks"] == n_lines == client.count("chunks").count
    assert counts["parents"] >= 1 and client.count("parents").count == counts["parents"]


def test_reindex_does_not_duplicate(index, corpus):
    client, dense, sparse, counts = index
    build_index(client, dense, sparse, corpus / "chunks.jsonl", corpus / "parents.jsonl", "chunks", "parents")
    assert client.count("chunks").count == counts["chunks"]


def test_bm25_finds_exact_identifier(index):
    client, dense, sparse, _ = index
    hits = hybrid_search(client, "chunks", dense, sparse, "PSLV-XL C22", k=1, mode="bm25")
    assert hits[0].payload["title"] == "IRNSS-1A"


def test_hybrid_returns_facts_chunk_with_citation(index):
    client, dense, sparse, _ = index
    # Plumbing test (tiny corpus + fake dense embedder): ranking quality is measured by evals.
    hits = hybrid_search(client, "chunks", dense, sparse, "What was the launch mass of GSAT-7?", k=3)
    facts = [h.payload for h in hits if h.payload["title"] == "GSAT-7" and h.payload["chunk_type"] == "facts"]
    assert facts, [h.payload["breadcrumb"] for h in hits]
    assert facts[0]["url"].endswith("GSAT-7") and facts[0]["breadcrumb"] == "GSAT-7 > Key facts"
    assert "2,650 kilograms" in facts[0]["content"]


def test_chunk_type_filter(index):
    client, dense, sparse, _ = index
    hits = hybrid_search(client, "chunks", dense, sparse, "Vikram lander", k=5, chunk_type="text")
    assert hits and all(h.payload["chunk_type"] == "text" for h in hits)


def test_parent_can_be_fetched_for_split_section(index):
    client, dense, sparse, _ = index
    hits = hybrid_search(client, "chunks", dense, sparse, "orbit raising liquid apogee motor", k=1)
    parent_id = hits[0].payload["parent_id"]
    assert parent_id
    parent = client.retrieve("parents", [point_id(parent_id)])[0].payload
    assert parent["title"] == "GSAT-7" and "apogee motor" in parent["content"]


def test_embedding_cache_avoids_repeat_calls(tmp_path):
    inner = FakeDense()
    cached = CachedEmbedder(inner, tmp_path / "cache.sqlite")
    first = cached.embed_documents(["a b c", "d e f"])
    second = cached.embed_documents(["a b c", "d e f"])
    assert inner.calls == 1 and cached.hits == 2 and cached.misses == 2
    assert all(abs(x - y) < 1e-6 for v1, v2 in zip(first, second) for x, y in zip(v1, v2))

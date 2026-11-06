"""Chunking variants under test (A/B)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from common import RAG_DIR  # noqa: F401  (sets sys.path)

from chunking import Chunk, ChunkConfig, chunk_document, est_tokens, parse_front_matter  # noqa: E402


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    kind: str                       # "structure" | "fixed"
    config: ChunkConfig | None = None
    with_breadcrumb: bool = True
    window: int = 400               # fixed-window size (tokens)
    overlap: int = 60               # fixed-window overlap (tokens)

    @property
    def chunks_collection(self) -> str:
        return f"eval_{self.name}_chunks"

    @property
    def parents_collection(self) -> str:
        return f"eval_{self.name}_parents"


VARIANTS = {v.name: v for v in [
    Variant("struct_350", "structure-aware, ~350-token children (production config)", "structure", ChunkConfig()),
    Variant("struct_200", "structure-aware, ~200-token children", "structure",
            ChunkConfig(child_target=200, child_max=280, child_min=80, tiny=40, table_target=180)),
    Variant("struct_600", "structure-aware, ~600-token children", "structure",
            ChunkConfig(child_target=600, child_max=750, child_min=200, tiny=60, table_target=500,
                        article_as_parent=1500, parent_max=2500)),
    Variant("struct_350_nocrumb", "as struct_350 but embedded WITHOUT the breadcrumb prefix", "structure",
            ChunkConfig(), with_breadcrumb=False),
    Variant("fixed_400", "naive baseline: fixed ~400-token windows, 60 overlap, ignores structure", "fixed"),
]}


def fixed_window_chunks(md: str, window: int = 400, overlap: int = 60) -> list[dict]:
    """Classic baseline: slide a fixed window over the raw article text (headings, tables and all)."""
    meta, body = parse_front_matter(md)
    title, doc_id = meta.get("title", ""), int(meta.get("pageid", 0))
    words = re.split(r"(\s+)", body.strip())  # keep whitespace tokens so text is reproduced exactly
    chunks, start, idx = [], 0, 0
    w_chars, o_chars = window * 4, overlap * 4
    text = "".join(words)
    while start < len(text):
        end = min(len(text), start + w_chars)
        if end < len(text):  # cut at whitespace
            cut = text.rfind(" ", start + w_chars // 2, end)
            end = cut if cut > 0 else end
        content = text[start:end].strip()
        if content:
            c = Chunk(chunk_id=f"{doc_id}:{idx:04d}", doc_id=doc_id, chunk_index=idx, chunk_type="text",
                      title=title, section_path=["(window)"], breadcrumb=title, content=content,
                      token_count=est_tokens(content), parent_id=None, url=meta.get("url", ""),
                      revid=meta.get("revid"), keywords=meta.get("keywords", []),
                      categories=meta.get("wikipedia_categories", []))
            chunks.append(asdict(c))
            idx += 1
        if end >= len(text):
            break
        start = max(end - o_chars, start + 1)
    for a, b in zip(chunks, chunks[1:]):
        a["next_id"], b["prev_id"] = b["chunk_id"], a["chunk_id"]
    return chunks


def chunk_for_variant(v: Variant, md: str) -> tuple[list[dict], list[dict]]:
    if v.kind == "fixed":
        return fixed_window_chunks(md, v.window, v.overlap), []
    chunks, parents = chunk_document(md, v.config)
    return [asdict(c) for c in chunks], [asdict(p) for p in parents]

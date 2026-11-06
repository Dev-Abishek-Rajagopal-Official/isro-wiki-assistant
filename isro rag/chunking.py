"""
Structure-aware chunking of the cleaned Wikipedia Markdown documents.

Design (sizes come from measuring the corpus: median leaf section ~150 tokens, long tail up to 28k):
  * Children = what gets embedded and searched (~150-400 tokens).
      - prose/lists are packed per top-level section, paragraph by paragraph:
          long sections are split at paragraph boundaries, tiny neighbouring sections are merged
          (their sub-headings are kept inline so no context is lost)
      - "Key facts" (infobox) -> one `facts` chunk
      - tables -> one `table` chunk, or row groups that each repeat the caption + header row
  * Parents = the top-level (##) section, or the whole article when the article is short.
    Parents are NOT embedded; at query time a retrieved child can be expanded to its parent.
    Parents above PARENT_MAX tokens are not stored (too big for the context) - those children
    use prev/next neighbours instead.
  * Every chunk carries a breadcrumb ("Article > Section > Subsection") that is prepended
    to the text before embedding, plus citation metadata (url, revid, section path).

Usage:
    python chunking.py                       # reads ../wiki documents, writes ./data/
    python chunking.py --docs <dir> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DOCS = HERE.parent / "wiki documents"
DEFAULT_OUT = HERE / "data"

# Token budget (approximate tokens, see est_tokens).
CHILD_TARGET = 350        # pack prose up to this size
CHILD_MAX = 450           # a single block above this is split further
CHILD_MIN = 120           # below this a chunk keeps absorbing the next section
TINY = 50                 # text chunks below this are merged into a neighbour
TABLE_TARGET = 300        # row-group size for large tables (numbers tokenise densely)
ARTICLE_AS_PARENT = 900   # short articles: the whole article is the parent
PARENT_MAX = 1500         # larger parents are not stored


@dataclass(frozen=True)
class ChunkConfig:
    """Size knobs, so evals can A/B different chunk sizes. Defaults = the production config."""
    child_target: int = CHILD_TARGET
    child_max: int = CHILD_MAX
    child_min: int = CHILD_MIN
    tiny: int = TINY
    table_target: int = TABLE_TARGET
    article_as_parent: int = ARTICLE_AS_PARENT
    parent_max: int = PARENT_MAX


DEFAULT_CONFIG = ChunkConfig()

LEAD = "Overview"
FACTS_HEADING = "Key facts"

FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
HEADING_RE = re.compile(r"^(#{1,6}) (.+)$")
LIST_RE = re.compile(r"^\s*(?:[-*]|\d+\.) ")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def est_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars per token for English). Good enough for sizing chunks;
    the exact count depends on the embedding model's tokenizer."""
    return max(1, round(len(text) / 4))


# --------------------------------------------------------------------------- data classes
@dataclass
class Block:
    kind: str                # paragraph | list | table | quote | facts
    text: str
    path: tuple[str, ...]    # section path below the article title, () = lead
    caption: str = ""        # tables only


@dataclass
class Chunk:
    chunk_id: str
    doc_id: int
    chunk_index: int
    chunk_type: str          # text | facts | table
    title: str
    section_path: list[str]
    breadcrumb: str
    content: str
    token_count: int
    parent_id: str | None
    prev_id: str | None = None
    next_id: str | None = None
    url: str = ""
    revid: int | None = None
    last_edited: str = ""
    short_description: str = ""
    keywords: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    def embedding_text(self) -> str:
        return f"{self.breadcrumb}\n\n{self.content}"


@dataclass
class Parent:
    parent_id: str
    doc_id: int
    title: str
    section_path: list[str]
    content: str
    token_count: int
    url: str


# --------------------------------------------------------------------------- parsing
def parse_front_matter(md: str) -> tuple[dict, str]:
    m = FRONT_MATTER_RE.match(md)
    if not m:
        return {}, md
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(": ")
        try:
            meta[key] = json.loads(value)
        except json.JSONDecodeError:
            meta[key] = value
    return meta, md[m.end():]


def parse_blocks(body: str) -> list[Block]:
    """Split the Markdown body into typed blocks, each tagged with its section path."""
    blocks: list[Block] = []
    path: list[str] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        h = HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            if level >= 2:  # level 1 is the article title
                path = path[: level - 2] + [h.group(2).strip()]
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            caption = ""
            if blocks and blocks[-1].kind == "paragraph" and blocks[-1].text.startswith("Table: ") \
                    and blocks[-1].path == tuple(path):
                caption = blocks.pop().text[len("Table: "):]
            blocks.append(Block("table", "\n".join(rows), tuple(path), caption))
            continue
        if LIST_RE.match(line):
            items = []
            while i < len(lines) and lines[i].strip() and (LIST_RE.match(lines[i]) or lines[i].startswith("  ")):
                items.append(lines[i])
                i += 1
            kind = "facts" if path and path[0] == FACTS_HEADING else "list"
            blocks.append(Block(kind, "\n".join(items), tuple(path)))
            continue
        kind = "quote" if line.startswith(">") else "paragraph"
        para = []
        while i < len(lines) and lines[i].strip() and not HEADING_RE.match(lines[i]) \
                and not lines[i].startswith("|") and not LIST_RE.match(lines[i]):
            para.append(lines[i])
            i += 1
        blocks.append(Block(kind, " ".join(para), tuple(path)))

    # Everything under "Key facts" is one facts block (wrapped values can look like paragraphs).
    merged: list[Block] = []
    for b in blocks:
        if b.path[:1] == (FACTS_HEADING,):
            if merged and merged[-1].kind == "facts" and merged[-1].path == b.path:
                merged[-1].text += "\n" + b.text
                continue
            b = Block("facts", b.text, b.path)
        merged.append(b)
    return merged


# --------------------------------------------------------------------------- splitting helpers
def split_long_text(text: str, target: int) -> list[str]:
    """Split an oversized paragraph at sentence boundaries."""
    parts, buf = [], ""
    for sent in SENTENCE_RE.split(text):
        if buf and est_tokens(buf + " " + sent) > target:
            parts.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        parts.append(buf)
    return parts


def split_list(text: str) -> list[str]:
    """Split a list into top-level items (nested lines stay with their item)."""
    items: list[str] = []
    for line in text.splitlines():
        if items and line.startswith("  "):
            items[-1] += "\n" + line
        else:
            items.append(line)
    return items


def units_for_block(b: Block, cfg: ChunkConfig = DEFAULT_CONFIG) -> list[Block]:
    """Break an oversized prose/list block into packable units."""
    if est_tokens(b.text) <= cfg.child_max:
        return [b]
    if b.kind == "list":
        return [Block("list", t, b.path) for t in split_list(b.text)]
    return [Block(b.kind, t, b.path) for t in split_long_text(b.text, cfg.child_target)]


def table_chunks(b: Block, cfg: ChunkConfig = DEFAULT_CONFIG) -> list[str]:
    lines = b.text.splitlines()
    header, rows = lines[:2], lines[2:]
    if header and header[0].startswith("| Column 1 |"):
        header[0] = header[0].replace("| Column 1 |", "| Item |", 1)
    head = ([f"Table: {b.caption}"] if b.caption else []) + header
    full = "\n".join(head + rows)
    if est_tokens(full) <= cfg.child_max or not rows:
        return [full]
    out, group = [], []
    for row in rows:
        if group and est_tokens("\n".join(head + group + [row])) > cfg.table_target:
            out.append("\n".join(head + group))
            group = []
        group.append(row)
    if group:
        out.append("\n".join(head + group))
    return out


def facts_chunks(b: Block, cfg: ChunkConfig = DEFAULT_CONFIG) -> list[str]:
    if est_tokens(b.text) <= cfg.child_max:
        return [b.text]
    out, group = [], []
    for line in b.text.splitlines():
        if group and est_tokens("\n".join(group + [line])) > cfg.child_target:
            out.append("\n".join(group))
            group = []
        group.append(line)
    if group:
        out.append("\n".join(group))
    return out


def common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for p in paths[1:]:
        n = 0
        while n < min(len(prefix), len(p)) and prefix[n] == p[n]:
            n += 1
        prefix = prefix[:n]
    return prefix


def render_block(b: Block) -> str:
    return b.text


def heading_line(path: tuple[str, ...]) -> str:
    return "#" * (len(path) + 1) + " " + path[-1]


def merge_tiny(raw: list[dict], cfg: ChunkConfig = DEFAULT_CONFIG) -> list[dict]:
    """Merge text chunks below TINY tokens into the next (else previous) text/facts chunk.
    Table chunks are never merged so their header-first layout stays intact."""
    i = 0
    while i < len(raw):
        r = raw[i]
        if r["type"] != "text" or est_tokens(r["content"]) >= cfg.tiny:
            i += 1
            continue
        for j in (i + 1, i - 1):
            if not 0 <= j < len(raw):
                continue
            into = raw[j]
            if into["type"] not in ("text", "facts") or \
                    est_tokens(r["content"] + into["content"]) > cfg.child_max:
                continue
            # The receiving chunk keeps its path (and so its citation); the tiny part keeps
            # its own heading inline.
            tiny = r["content"]
            if r["path"] and r["path"] != into["path"]:
                tiny = heading_line(r["path"]) + "\n\n" + tiny
            content = tiny + "\n\n" + into["content"] if j > i else into["content"] + "\n\n" + tiny
            raw[j] = {**into, "content": content}
            del raw[i]
            break
        else:
            i += 1
    return raw


# --------------------------------------------------------------------------- chunking
def chunk_document(md: str, cfg: ChunkConfig = DEFAULT_CONFIG) -> tuple[list[Chunk], list[Parent]]:
    meta, body = parse_front_matter(md)
    title = meta.get("title", "")
    doc_id = int(meta.get("pageid", 0))
    blocks = parse_blocks(body)

    # Group blocks by top-level section (the parent unit). The lead is its own group.
    groups: list[tuple[tuple[str, ...], list[Block]]] = []
    for b in blocks:
        key = b.path[:1]
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(b)

    def group_text(gblocks: list[Block]) -> str:
        out, last = [], None
        for b in gblocks:
            if b.path != last and b.path:
                out.append("#" * (len(b.path) + 1) + " " + b.path[-1])
                last = b.path
            out.append((f"Table: {b.caption}\n" if b.caption else "") + b.text)
        return "\n\n".join(out)

    article_tokens = est_tokens(body)
    raw: list[dict] = []  # chunks before ids are assigned

    for gkey, gblocks in groups:
        pending: list[Block] = []

        def flush() -> None:
            if not pending:
                return
            paths = [u.path for u in pending]
            prefix = common_prefix(paths)
            parts, last = [], prefix  # headings below the chunk's own path are kept inline
            for u in pending:
                if u.path != last:
                    # keep sub-headings of merged sections inline
                    parts.append("#" * (len(u.path) + 1) + " " + u.path[-1])
                    last = u.path
                parts.append(render_block(u))
            raw.append({"type": "text", "path": prefix, "content": "\n\n".join(parts), "group": gkey})
            pending.clear()

        for b in gblocks:
            if b.kind == "facts":
                flush()
                for c in facts_chunks(b, cfg):
                    raw.append({"type": "facts", "path": b.path, "content": c, "group": gkey})
                continue
            if b.kind == "table":
                flush()
                for c in table_chunks(b, cfg):
                    raw.append({"type": "table", "path": b.path, "content": c, "group": gkey})
                continue
            for u in units_for_block(b, cfg):
                size = sum(est_tokens(p.text) for p in pending)
                if pending and (size + est_tokens(u.text) > cfg.child_target
                                or (u.path != pending[-1].path and size >= cfg.child_min)):
                    flush()
                pending.append(u)
        flush()

    raw = merge_tiny(raw, cfg)

    # Parents: whole article if short, else each top-level section (if not too big).
    parents: dict[tuple[str, ...], Parent] = {}
    group_chunk_counts = Counter(r["group"] for r in raw)
    if article_tokens <= cfg.article_as_parent:
        if len(raw) > 1:
            text = group_text(blocks)
            parents[("*",)] = Parent(f"{doc_id}:p0", doc_id, title, [], text, est_tokens(text), meta.get("url", ""))
    else:
        for n, (gkey, gblocks) in enumerate(groups, 1):
            if group_chunk_counts[gkey] < 2:
                continue  # the single chunk already is the whole section
            text = group_text(gblocks)
            if est_tokens(text) > cfg.parent_max:
                continue
            parents[gkey] = Parent(f"{doc_id}:p{n}", doc_id, title, list(gkey) or [LEAD], text,
                                   est_tokens(text), meta.get("url", ""))

    chunks: list[Chunk] = []
    for idx, r in enumerate(raw):
        path = list(r["path"]) or [LEAD]
        parent = parents.get(("*",)) or parents.get(r["group"])
        chunks.append(Chunk(
            chunk_id=f"{doc_id}:{idx:04d}",
            doc_id=doc_id,
            chunk_index=idx,
            chunk_type=r["type"],
            title=title,
            section_path=path,
            breadcrumb=" > ".join([title] + path),
            content=r["content"],
            token_count=est_tokens(r["content"]),
            parent_id=parent.parent_id if parent else None,
            url=meta.get("url", ""),
            revid=meta.get("revid"),
            last_edited=meta.get("last_edited", ""),
            short_description=meta.get("short_description", ""),
            keywords=meta.get("keywords", []),
            categories=meta.get("wikipedia_categories", []),
        ))
    for a, b in zip(chunks, chunks[1:]):
        a.next_id, b.prev_id = b.chunk_id, a.chunk_id
    return chunks, list(parents.values())


def document_paths(docs: Path) -> list[Path]:
    """The article files in a documents folder (the folder's README.md is documentation, not an article)."""
    return sorted(p for p in docs.glob("*.md") if p.name.lower() != "readme.md")


# --------------------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    n_docs = 0
    sizes: dict[str, list[int]] = {"text": [], "facts": [], "table": []}
    n_parents = 0
    with open(args.out / "chunks.jsonl", "w", encoding="utf-8") as cf, \
            open(args.out / "parents.jsonl", "w", encoding="utf-8") as pf:
        for path in document_paths(args.docs):  # one document in memory at a time
            chunks, parents = chunk_document(path.read_text(encoding="utf-8"))
            for c in chunks:
                cf.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
                sizes[c.chunk_type].append(c.token_count)
            for p in parents:
                pf.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
            n_parents += len(parents)
            n_docs += 1

    all_sizes = [s for v in sizes.values() for s in v]
    print(f"{n_docs} documents -> {len(all_sizes)} chunks, {n_parents} parents")
    for kind, v in sizes.items():
        if v:
            v = sorted(v)
            print(f"  {kind:<6} n={len(v):5d}  median={int(statistics.median(v)):4d}  "
                  f"p90={v[int(.9 * (len(v) - 1))]:4d}  max={v[-1]:4d}  <60={sum(x < 60 for x in v)}")
    print(f"Wrote {args.out / 'chunks.jsonl'} and {args.out / 'parents.jsonl'}")


if __name__ == "__main__":
    main()

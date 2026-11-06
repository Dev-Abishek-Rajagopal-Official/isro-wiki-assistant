"""
Build the evaluation question set from the cleaned documents (not from chunks, so every chunking
variant is judged on the same questions).

For each sampled passage (prose / Key facts / table) gpt-6-luna writes:
    question  - self-contained (names the entity), answerable from the passage alone
    answer    - short reference answer
    evidence  - a VERBATIM excerpt of the passage that contains the answer
Items whose evidence is not found verbatim in the passage are rejected.
Out-of-scope questions are added and checked to be absent from the corpus.

Usage:
    uv run python rag_evals/build_dataset.py --n 60
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import EVAL_SET, LLM, RAG_DIR, contains_evidence, log, normalize, record

from chunking import est_tokens, parse_blocks, parse_front_matter  # noqa: E402

DOCS = RAG_DIR.parent / "wiki documents"

# (question, term that must NOT appear in the corpus)
OUT_OF_SCOPE = [
    ("How many astronauts flew on the Apollo 13 mission?", "apollo 13"),
    ("What is the payload capacity of SpaceX's Starship to low Earth orbit?", "starship"),
    ("Who won the 2018 FIFA World Cup?", "fifa"),
    ("When did the James Webb Space Telescope reach the L2 point?", "james webb"),
    ("What is the capital city of Australia?", "canberra"),
    ("Which company manufactures the Falcon Heavy rocket?", "falcon heavy"),
    ("What is the boiling point of liquid nitrogen?", "liquid nitrogen"),
    ("Who wrote the novel Pride and Prejudice?", "pride and prejudice"),
]

INSTRUCTIONS = """You create evaluation questions for a retrieval-augmented QA system about the Indian space programme.
Given a passage from a Wikipedia article, write ONE question that:
- is fully self-contained: always name the specific subject (e.g. "GSAT-7", "Vikram Sarabhai"), never "this satellite" or "the article";
- can be answered from the passage alone, with a specific fact (number, date, name, place, reason);
- sounds like a real user question, without copying long phrases from the passage.
Return JSON: {"question": "...", "answer": "short reference answer (one sentence)",
"evidence": "an excerpt copied EXACTLY, character for character, from the passage that contains the answer (5-30 words; for a table copy one cell value or a short run of text from one row; for a fact list copy one line without the leading dash)"}"""


def passages(path: Path) -> list[dict]:
    """Candidate passages of one document, tagged with type and section."""
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    blocks = parse_blocks(body)
    out = []
    base = {"title": meta.get("title", ""), "url": meta.get("url", "")}
    for b in blocks:
        if b.kind == "facts" and est_tokens(b.text) >= 40:
            out.append({**base, "type": "facts", "section": " > ".join(b.path), "text": b.text})
        elif b.kind == "table":
            lines = b.text.splitlines()
            if len(lines) >= 4:
                rows = lines[2:]
                start = random.randrange(max(1, len(rows) - 8))
                text = "\n".join(lines[:2] + rows[start:start + 8])
                out.append({**base, "type": "table", "section": " > ".join(b.path) or "Overview", "text": text})
    # prose: consecutive paragraphs of one section, 80-350 tokens
    cur, path_ = [], None
    for b in blocks + [None]:
        if b is None or b.kind not in ("paragraph", "list") or b.path != path_:
            text = "\n\n".join(cur)
            if 80 <= est_tokens(text) <= 350:
                out.append({**base, "type": "text", "section": " > ".join(path_ or ()) or "Overview", "text": text})
            elif est_tokens(text) > 350:
                out.append({**base, "type": "text", "section": " > ".join(path_ or ()) or "Overview",
                            "text": text[:1400].rsplit(". ", 1)[0] + "."})
            cur, path_ = [], (b.path if b else None)
        if b is not None and b.kind in ("paragraph", "list") and not b.text.startswith("_"):
            cur.append(b.text)
            path_ = b.path
    return out


def make_item(llm: LLM, p: dict) -> dict | None:
    prompt = f"Article: {p['title']}\nSection: {p['section']}\n\nPassage:\n{p['text']}"
    for _ in range(2):
        try:
            r = llm.generate(INSTRUCTIONS, prompt, json_mode=True)
            q = json.loads(r["text"])
        except Exception as e:  # noqa: BLE001
            log(f"[dataset] generation error for {p['title']}: {type(e).__name__}: {e}")
            continue
        ev = (q.get("evidence") or "").strip().lstrip("- ").strip()
        if q.get("question") and q.get("answer") and len(ev) >= 8 and contains_evidence(p["text"], ev):
            return {"question": q["question"].strip(), "reference_answer": q["answer"].strip(), "evidence": ev,
                    "type": p["type"], "source_title": p["title"], "source_section": p["section"],
                    "source_url": p["url"], "in_scope": True}
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="number of in-scope questions")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--mix", default="text:0.55,facts:0.25,table:0.20")
    args = ap.parse_args()
    random.seed(args.seed)

    mix = {k: float(v) for k, v in (x.split(":") for x in args.mix.split(","))}
    docs = sorted(DOCS.glob("*.md"))
    random.shuffle(docs)
    pools: dict[str, list[dict]] = {k: [] for k in mix}
    for d in docs:  # one passage per type per document -> questions spread over many articles
        by_type: dict[str, list[dict]] = {}
        for p in passages(d):
            by_type.setdefault(p["type"], []).append(p)
        for t, ps in by_type.items():
            if t in pools:
                pools[t].append(random.choice(ps))
    # oversample ~40% to absorb rejected generations
    targets = {t: round(args.n * w) for t, w in mix.items()}
    chosen = [p for t, n in targets.items() for p in pools[t][: int(n * 1.4) + 2]]
    log(f"[dataset] sampling {len(chosen)} passages for targets {targets} from {len(docs)} documents")

    llm = LLM()
    with ThreadPoolExecutor(max_workers=6) as pool:
        items = [i for i in pool.map(lambda p: make_item(llm, p), chosen) if i]
    final: list[dict] = []
    for t, n in targets.items():
        final += [i for i in items if i["type"] == t][:n]

    corpus = " ".join(normalize(p.read_text(encoding="utf-8")) for p in docs)
    oos = [{"question": q, "reference_answer": "Not covered by the documents.", "evidence": "", "type": "out_of_scope",
            "source_title": "", "source_section": "", "source_url": "", "in_scope": False}
           for q, term in OUT_OF_SCOPE if term not in corpus]

    rows = final + oos
    for i, r in enumerate(rows, 1):
        r["id"] = f"q{i:03d}"
    with open(EVAL_SET, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    counts = {t: sum(r["type"] == t for r in rows) for t in [*mix, "out_of_scope"]}
    record("dataset", "eval_set", {"n_questions": len(rows)},
           notes=f"types={counts}; rejected={len(chosen) - len(items)} of {len(chosen)} generations; model={llm.model}")
    log(f"[dataset] wrote {EVAL_SET}")


if __name__ == "__main__":
    main()

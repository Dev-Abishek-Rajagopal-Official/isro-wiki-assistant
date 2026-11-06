"""
Build results/REPORT.md from experiments.csv + per-question details.

Sections: retrieval A/B (all variants/pipelines), RAGAS end-to-end, and a same-question comparison
of every RAGAS pipeline on the questions they all answered (fair A/B when runs used different subsets).

Usage:
    uv run python rag_evals/report.py
"""

from __future__ import annotations

import csv
import statistics

from common import DETAILS_DIR, EXPERIMENTS_CSV, RESULTS_DIR, log, read_jsonl

RAGAS_METRICS = ["answer_accuracy", "factual_correctness", "faithfulness", "context_recall", "answer_relevancy"]


def f(v, nd=2):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "–"


def label(name: str) -> str:
    """Pipeline names contain '|', which would break Markdown tables."""
    return name.replace(" | ", " · ").replace("|-|-", "").replace("|", " · ")


def latest(rows: list[dict]) -> list[dict]:
    """Keep the last row per variant (re-runs supersede), drop smoke tests."""
    out: dict[str, dict] = {}
    for r in rows:
        if "SMOKE TEST" in r["notes"]:
            continue
        out[r["variant"]] = r
    return list(out.values())


def main() -> None:
    with open(EXPERIMENTS_CSV, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    retrieval = latest([r for r in rows if r["stage"] == "retrieval"])
    ragas = latest([r for r in rows if r["stage"] == "ragas"])
    index = latest([r for r in rows if r["stage"] == "index"])
    dataset = latest([r for r in rows if r["stage"] == "dataset"])

    md = ["# RAG evaluation report", ""]
    if dataset:
        md += [f"Eval set: {dataset[-1]['n_questions']} questions ({dataset[-1]['notes']}).", ""]

    md += ["## 1. Chunking variants", "", "| Variant | Chunks | Notes |", "|---|---|---|"]
    md += [f"| {r['variant']} | {r['n_chunks']} | {r['notes']} |" for r in index]

    md += ["", "## 2. Retrieval A/B (evidence sentence found in retrieved chunks; 60 in-scope questions)", "",
           "| Variant + pipeline | R@1 | R@3 | **R@5** | R@10 | MRR@10 | Doc hit@5 | Context tokens | Latency ms |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(retrieval, key=lambda r: (-float(r["evidence_recall@5"]), -float(r["mrr@10"]))):
        md.append(f"| {label(r['variant'])} | {f(r['evidence_recall@1'])} | {f(r['evidence_recall@3'])} | "
                  f"**{f(r['evidence_recall@5'])}** | {f(r['evidence_recall@10'])} | {f(r['mrr@10'])} | "
                  f"{f(r['doc_hit@5'])} | {f(r['avg_context_tokens'], 0)} | {f(r['avg_latency_ms'], 0)} |")

    md += ["", "## 3. End-to-end RAGAS (generator + judge: gpt-6-luna)", "",
           "| Pipeline | Questions | Answer accuracy | Factual correctness (recall) | Faithfulness | Context recall | "
           "Answer relevancy | OOS refused | False refusals | Answer latency s |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in ragas:
        md.append(f"| {label(r['variant'])} | {int(r['n_questions']) - 5} + 5 OOS | {f(r['answer_accuracy'])} | "
                  f"{f(r['factual_correctness'])} | {f(r['faithfulness'])} | {f(r['context_recall'])} | "
                  f"{f(r['answer_relevancy'])} | {f(r['oos_refusal_rate'])} | {f(r['false_refusal_rate'])} | "
                  f"{f(r['avg_answer_latency_s'], 1)} |")

    # Same-question comparison from details files.
    details = {}
    for r in ragas:
        safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in f"ragas__{r['variant']}")
        path = DETAILS_DIR / f"{safe}.jsonl"
        if path.exists():
            details[r["variant"]] = {d["id"]: d for d in read_jsonl(path) if d.get("scores")}
    if len(details) >= 2:
        common_ids = sorted(set.intersection(*(set(d) for d in details.values())))
        md += ["", f"## 4. Same-question comparison ({len(common_ids)} in-scope questions answered by every pipeline)",
               "", "| Pipeline | " + " | ".join(RAGAS_METRICS) + " |", "|---|" + "---|" * len(RAGAS_METRICS)]
        for name, d in details.items():
            cells = []
            for m in RAGAS_METRICS:
                vals = [d[i]["scores"].get(m) for i in common_ids if d[i]["scores"].get(m) is not None]
                cells.append(f(statistics.mean(vals)) if vals else "–")
            md.append(f"| {label(name)} | " + " | ".join(cells) + " |")
        md += ["", f"Question ids: {', '.join(common_ids)}"]

    conclusions = RESULTS_DIR / "CONCLUSIONS.md"  # hand-written interpretation, kept separate from the data
    if conclusions.exists():
        md += ["", conclusions.read_text(encoding="utf-8").strip()]

    out = RESULTS_DIR / "REPORT.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    log(f"[report] wrote {out}")


if __name__ == "__main__":
    main()

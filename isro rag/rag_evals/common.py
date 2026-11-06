"""Shared helpers for the RAG evaluations: paths, LLM client, retrieval stack, experiment log."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RAG_DIR = EVAL_DIR.parent
sys.path.insert(0, str(RAG_DIR))  # import chunking, index, embeddings, config, search

import config  # noqa: E402  (loads .env)
from config import get_settings  # noqa: E402

DATA_DIR = EVAL_DIR / "data"
RESULTS_DIR = EVAL_DIR / "results"
DETAILS_DIR = RESULTS_DIR / "details"
EVAL_SET = DATA_DIR / "eval_set.jsonl"
EXPERIMENTS_CSV = RESULTS_DIR / "experiments.csv"
EXPERIMENTS_LOG = RESULTS_DIR / "experiments.log"
for d in (DATA_DIR, RESULTS_DIR, DETAILS_DIR):
    d.mkdir(parents=True, exist_ok=True)

LLM_MODEL = os.getenv("EVAL_LLM_MODEL", "gpt-6-luna")
V1_BASE_URL = os.getenv("AZURE_OPENAI_V1_BASE_URL", "")

# One fixed column set for every experiment row, so all findings live in one CSV.
CSV_COLUMNS = [
    "timestamp", "stage", "variant", "chunk_config", "retrieval", "reranker", "parent_expansion",
    "n_questions", "n_chunks",
    "evidence_recall@1", "evidence_recall@3", "evidence_recall@5", "evidence_recall@10", "mrr@10",
    "doc_hit@5", "avg_context_tokens", "avg_latency_ms",
    "faithfulness", "answer_relevancy", "context_precision", "context_recall", "factual_correctness",
    "answer_accuracy",
    "oos_refusal_rate", "false_refusal_rate", "avg_answer_latency_s", "llm_input_tokens", "llm_output_tokens",
    "notes",
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    """Human-readable experiment log (and console)."""
    line = f"{now()}  {msg}"
    print(line, flush=True)
    with open(EXPERIMENTS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def record(stage: str, variant: str, metrics: dict, notes: str = "") -> None:
    """Append one finding to experiments.csv immediately (and summarise it in the log)."""
    _migrate_csv_header()
    new = not EXPERIMENTS_CSV.exists()
    row = {c: "" for c in CSV_COLUMNS}
    row.update({"timestamp": now(), "stage": stage, "variant": variant, "notes": notes})
    for k, v in metrics.items():
        if k not in row:
            raise KeyError(f"unknown metric column {k!r}")
        row[k] = round(v, 4) if isinstance(v, float) else v
    with open(EXPERIMENTS_CSV, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
    shown = {k: row[k] for k in CSV_COLUMNS[3:-1] if row[k] != ""}
    log(f"[{stage}] {variant}: " + ", ".join(f"{k}={v}" for k, v in shown.items()) + (f"  ({notes})" if notes else ""))


def _migrate_csv_header() -> None:
    """If columns were added since the CSV was created, rewrite it with the new header (rows kept)."""
    if not EXPERIMENTS_CSV.exists():
        return
    with open(EXPERIMENTS_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == CSV_COLUMNS:
            return
        rows = list(reader)
    with open(EXPERIMENTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in CSV_COLUMNS} for r in rows)


def write_details(name: str, rows: list[dict]) -> Path:
    path = DETAILS_DIR / f"{re.sub(r'[^\w.-]+', '_', name)}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return path


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# --------------------------------------------------------------------------- LLM (Responses API)
class LLM:
    """gpt-6-luna via the Azure AI Foundry OpenAI v1 endpoint (Responses API)."""

    def __init__(self, model: str = LLM_MODEL) -> None:
        from openai import OpenAI

        s = get_settings()
        if not (V1_BASE_URL and s.azure_api_key):
            raise RuntimeError("Set AZURE_OPENAI_V1_BASE_URL and AZURE_OPENAI_API_KEY in isro rag/.env")
        self.client = OpenAI(base_url=V1_BASE_URL, api_key=s.azure_api_key, max_retries=6, timeout=120)
        self.model = model

    def generate(self, instructions: str, prompt: str, json_mode: bool = False) -> dict:
        kwargs = {}
        if json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}
            if "json" not in prompt.lower():  # the API requires the word in the input itself
                prompt += "\n\nRespond with the JSON object only."
        t0 = time.time()
        r = self.client.responses.create(model=self.model, instructions=instructions, input=prompt, **kwargs)
        return {
            "text": r.output_text,
            "latency_s": time.time() - t0,
            "input_tokens": getattr(r.usage, "input_tokens", 0),
            "output_tokens": getattr(r.usage, "output_tokens", 0),
        }


# --------------------------------------------------------------------------- evidence matching
def normalize(text: str) -> str:
    text = text.lower().replace("|", " ").replace("*", " ").replace("_", " ")
    text = re.sub(r"[‐-―]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_evidence(context: str, evidence: str) -> bool:
    return normalize(evidence) in normalize(context)

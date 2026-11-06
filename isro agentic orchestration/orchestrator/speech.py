"""
Azure Speech - speech-to-text (Fast Transcription REST API, synchronous, for short questions).

A phrase list of ISRO names (missions, satellites, rockets, centres; built from the corpus titles) biases
recognition: without it 'Cartosat-3' was transcribed as 'Cardasat-3'.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache

import httpx

from .config import ROOT, get_settings

API_VERSION = "2025-10-15"  # phraseList needs this version (2024-11-15 rejects it)
MAX_PHRASES = 400
CORE_PHRASES = ["ISRO", "PSLV", "GSLV", "LVM3", "SSLV", "Chandrayaan", "Mangalyaan", "Gaganyaan", "Aditya-L1",
                "Cartosat", "NavIC", "IRNSS", "GSAT", "INSAT", "RISAT", "Oceansat", "Resourcesat", "AstroSat",
                "XPoSat", "NISAR", "Sriharikota", "Satish Dhawan", "Vikram Sarabhai", "Vikram lander",
                "Pragyan rover", "VSSC", "URSC", "NRSC", "Bhuvan", "Shukrayaan"]


@lru_cache(maxsize=1)
def phrase_list() -> list[str]:
    phrases = list(CORE_PHRASES)
    meta = ROOT.parent / "wiki documents" / "wiki_metadata.csv"
    if meta.exists():
        with open(meta, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                title = re.sub(r"\s*\(.*?\)", "", row["title"]).strip()
                if 2 < len(title) <= 40 and len(title.split()) <= 4 and not title.lower().startswith("list of"):
                    phrases.append(title)
    seen, out = set(), []
    for p in phrases:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out[:MAX_PHRASES]


async def transcribe(audio: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> dict:
    """Returns {"text", "duration_ms", "phrases"}; raises RuntimeError with a readable message on failure."""
    s = get_settings()
    if not (s.speech_endpoint and s.speech_key):
        raise RuntimeError("Set SPEECH_ENDPOINT and SPEECH_KEY in .env")
    if not audio:
        raise RuntimeError("Empty audio")
    url = f"{s.speech_endpoint}/speechtotext/transcriptions:transcribe"
    definition = {"locales": list(s.speech_locales), "phraseList": {"phrases": phrase_list()}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
        r = await client.post(url, params={"api-version": API_VERSION},
                              headers={"Ocp-Apim-Subscription-Key": s.speech_key},
                              files={"audio": (filename, audio, content_type)},
                              data={"definition": json.dumps(definition)})
    if r.status_code != 200:
        raise RuntimeError(f"Azure Speech error HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    text = " ".join(p.get("text", "") for p in body.get("combinedPhrases", [])).strip()
    return {"text": text, "duration_ms": body.get("durationMilliseconds"), "phrases": len(definition["phraseList"]["phrases"])}

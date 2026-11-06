"""
Azure Speech - speech-to-text (Fast Transcription REST API, synchronous, for short questions).

A phrase list of ISRO names (missions, satellites, rockets, centres; built from the corpus titles) biases
recognition: without it 'Cartosat-3' was transcribed as 'Cardasat-3'.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from functools import lru_cache

import httpx

from .config import ROOT, get_settings

log = logging.getLogger(__name__)
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


class SpeechError(RuntimeError):
    """A transcription problem the user can act on - str(error) is a message meant for the user."""


NO_SPEECH = ("I couldn't hear a question in that recording. Check that the right microphone is selected and "
             "allowed in the browser, speak for a second or two, then try again - or type your question.")


def _no_language(r: httpx.Response) -> bool:
    return r.status_code == 422 and "NoLanguageIdentified" in r.text


async def transcribe(audio: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> dict:
    """Returns {"text", "duration_ms", "phrases"}; raises SpeechError (user-facing message) on failure."""
    s = get_settings()
    if not (s.speech_endpoint and s.speech_key):
        raise SpeechError("Voice questions are not configured on this server (SPEECH_ENDPOINT / SPEECH_KEY).")
    if not audio:
        raise SpeechError(NO_SPEECH)
    url = f"{s.speech_endpoint}/speechtotext/transcriptions:transcribe"
    locales = list(s.speech_locales)
    phrases = phrase_list()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
        async def post(locs: list[str]) -> httpx.Response:
            definition = {"locales": locs, "phraseList": {"phrases": phrases}}
            return await client.post(url, params={"api-version": API_VERSION},
                                     headers={"Ocp-Apim-Subscription-Key": s.speech_key},
                                     files={"audio": (filename, audio, content_type)},
                                     data={"definition": json.dumps(definition)})

        r = await post(locales)
        # With several locales Azure first identifies the language and gives up on short / quiet clips.
        # Our locales are English variants, so transcribing with the first one alone is the right fallback.
        if _no_language(r) and len(locales) > 1:
            log.info("speech: no language identified with %s, retrying with %s", locales, locales[:1])
            r = await post(locales[:1])

    if _no_language(r):
        raise SpeechError(NO_SPEECH)
    if r.status_code != 200:
        log.warning("speech: Azure HTTP %s: %s", r.status_code, r.text[:300])
        raise SpeechError(f"Speech-to-text failed (Azure HTTP {r.status_code}). Please try again or type your question.")
    body = r.json()
    text = " ".join(p.get("text", "") for p in body.get("combinedPhrases", [])).strip()
    if not text:
        raise SpeechError(NO_SPEECH)
    return {"text": text, "duration_ms": body.get("durationMilliseconds"), "phrases": len(phrases)}

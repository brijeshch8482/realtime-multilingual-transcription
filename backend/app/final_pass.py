"""Accurate second pass over the whole recording (runs once, when the user stops).

Gemini Live gives a fast word-by-word draft, but its automatic language ID is
fragile for some languages (e.g. Kannada audio sometimes comes back in Burmese
or as English-sounding words). A regular Gemini model listening to the full
recording identifies languages reliably and writes each one in its own script,
so its result replaces the draft. If it fails (quota, timeout), the draft stays.
"""

import asyncio
import io
import json
import logging
import time
import wave

from google import genai
from google.genai import types

from .config import settings
from .normalize import looks_translated

log = logging.getLogger("final_pass")

SAMPLE_RATE = 16000
# Inline requests are limited to ~20 MB; 16 kHz PCM16 is 32 KB/s -> cap ~9 minutes.
MAX_SECONDS = 540
HEDGE_AFTER = 6.0  # seconds before also asking the next model in the chain

PROMPT = (
    "Transcribe this speech recording exactly as spoken. Speakers often mix English "
    "with another language (any language). "
    "SCRIPT RULES (mandatory): English words in Latin letters. Every non-English word "
    "MUST be written in that language's native script, never romanised: Hindi/Marathi "
    "in Devanagari (देवनागरी), Kannada (ಕನ್ನಡ), Tamil (தமிழ்), Telugu (తెలుగు), "
    "Bengali (বাংলা), Gujarati (ગુજરાતી), Malayalam (മലയാളം), Punjabi (ਪੰਜਾਬੀ), "
    "Urdu/Arabic (اردو), Chinese, Japanese, Korean etc.; Latin-script languages "
    "(Spanish, French...) stay in Latin letters. Do not translate, summarise or add "
    "anything. If there is no speech, return an empty transcript. "
    "Also list the ISO 639-1 codes of the languages spoken, most used first."
)

_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "transcript": types.Schema(type=types.Type.STRING),
        "languages": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
    },
    required=["transcript", "languages"],
)

_client: genai.Client | None = None


def enabled() -> bool:
    return bool(settings.gemini_api_key and settings.final_models)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=max(10_000, int(settings.final_timeout * 1000))),
        )
    return _client


def _to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _parse(raw: str) -> tuple[str, list[str]] | None:
    data = json.loads(raw or "{}")
    text = " ".join(str(data.get("transcript", "")).split())
    langs: list[str] = []
    for c in data.get("languages", []):
        c = str(c).strip().lower()
        if 2 <= len(c) <= 3 and c.isalpha() and c not in langs:
            langs.append(c)
    return (text, langs[:6]) if text else None


def _instruction(draft: str, lang_hint: str | None = None) -> str:
    hint = ""
    if lang_hint:
        hint = (
            f" The speaker selected '{lang_hint}' (BCP-47) as their main language; they "
            "typically mix it with English, so expect mostly that language."
        )
    if not draft.strip():
        return "Transcribe this recording." + hint
    return (
        "Transcribe this recording." + hint + " For reference, a fast streaming recognizer produced "
        "this draft, which may contain mistakes, missing words or even the wrong language "
        "- trust the audio over the draft, but follow its script choices for English "
        f"words when they match what is said:\n<draft>{draft[:4000]}</draft>"
    )


async def _attempt(
    model: str, thinking: str, wav: bytes, draft: str, lang_hint: str | None, timeout: float
):
    resp = await asyncio.wait_for(
        _get_client().aio.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                _instruction(draft, lang_hint),
            ],
            config=types.GenerateContentConfig(
                system_instruction=PROMPT,
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
            ),
        ),
        timeout=timeout,
    )
    return _parse(resp.text)


async def transcribe_recording(
    pcm: bytes, draft: str = "", lang_hint: str | None = None
) -> tuple[str, list[str]] | None:
    """Return (transcript, languages), or None if unavailable / every model failed.

    Models in FINAL_MODELS are tried as a hedged chain: if the current model fails
    (quota/overload) the next starts at once, and if it is merely slow, the next is
    started after HEDGE_AFTER seconds as well - the first good answer wins."""
    seconds = len(pcm) / (2 * SAMPLE_RATE)
    if not enabled() or seconds < 0.5:
        return None
    if seconds > MAX_SECONDS:
        log.info("recording too long for inline final pass (%.0fs); keeping draft", seconds)
        return None
    wav = _to_wav(pcm)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.final_timeout
    queue = list(settings.final_models)
    running: dict[asyncio.Task, str] = {}

    def launch():
        model, thinking = queue.pop(0)
        task = asyncio.create_task(
            _attempt(model, thinking, wav, draft, lang_hint, max(2.0, deadline - loop.time()))
        )
        running[task] = model

    try:
        launch()
        while running:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            done, _ = await asyncio.wait(
                set(running),
                timeout=min(remaining, HEDGE_AFTER) if queue else remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                if queue:
                    log.info("final pass: %s is slow, also asking %s", ", ".join(running.values()), queue[0][0])
                    launch()
                continue
            for task in done:
                model = running.pop(task)
                try:
                    result = task.result()
                except Exception as e:
                    # 429 quota / 503 overloaded / timeout -> next model
                    log.warning("final pass: %s failed (%s)", model, str(e)[:160])
                    result = False
                if result is None:
                    log.info("final pass by %s: no speech (%.1fs audio)", model, seconds)
                    return None
                if result:
                    text, langs = result
                    if draft and looks_translated(draft, text):
                        log.warning("final pass: %s translated the speech; rejected", model)
                    else:
                        log.info("final pass by %s (%.1fs audio)", model, seconds)
                        return result
                if queue and not running:
                    launch()
        log.warning("final pass unavailable; keeping live draft")
        return None
    finally:
        for task in running:
            task.cancel()

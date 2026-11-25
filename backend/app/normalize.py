"""Script normalisation for code-mixed transcripts (any language + English).

Gemini Live is inconsistent about script: English words spoken with an Indian
accent come back in the native script ("प्रोजेक्ट", "ಮೀಟಿಂಗ್"), and some speech
comes back romanised ("aur fir dinner ke liye"). This pass rewrites each
committed phrase so English is in Latin script and every other language is in
its own native script - it never translates. If it is slow or fails, the raw
transcript is kept.
"""

import asyncio
import logging
import re

from google import genai
from google.genai import types

from .config import settings
from .textutil import detect_languages_by_script, has_non_latin_script

log = logging.getLogger("normalize")

HEDGE_AFTER = 1.0  # seconds before also asking the backup model

PROMPT = (
    "You fix the script of a code-mixed speech transcript in which the speaker mixes "
    "English with another language (for example Hindi, Kannada, Tamil, Telugu, Bengali, "
    "Marathi, Gujarati, Malayalam, Punjabi, Urdu, Arabic, Japanese...). "
    "Write every English word (including English loanwords such as meeting, project, "
    "deadline, please, office, dinner) in Latin script with correct English spelling. "
    "Write every word of the other language in that language's own native script, "
    "including words that were written in Roman letters "
    "(e.g. 'aur fir dinner ke liye' -> 'और फिर dinner के लिए'). "
    "Never translate, never add, remove or reorder words, keep punctuation and numbers. "
    "If there is nothing to change, return the input unchanged. "
    "Output only the corrected transcript."
)

# Common Hindi/Urdu words written in Roman script (the most frequent kind of
# romanised output); used to decide whether a Latin-only phrase needs fixing.
ROMAN_HINDI = re.compile(
    r"\b(aur|hai|hain|ke|ki|ka|ko|se|mein|nahi|nahin|liye|kya|hum|tum|aap|bhi|toh|"
    r"kal|aaj|abhi|chalo|chalenge|karna|karo|raha|rahi|tha|thi|wala|wali|mera|meri|"
    r"tera|hamara|kyun|kaise|kahan|jab|phir|fir|accha|acha|theek|haan)\b",
    re.IGNORECASE,
)

# Very common Hindi function words (Devanagari). If these disappear from a rewrite,
# the model translated instead of fixing the script.
HINDI_FUNCTION_WORDS = re.compile(
    "(?<![ऀ-ॿ])("
    "है|हैं|था|थी|थे|का|की|के|को|से|में|पर|और|नहीं|क्या|क्यों|कैसे|हो|रहा|रही|रहे|"
    "मैं|हम|तुम|आप|मेरा|मेरी|तेरा|हमारा|यह|ये|वह|वो|भी|तो|कल|आज|अभी|यार|भाई|ठीक"
    ")(?![ऀ-ॿ])"
)

_client: genai.Client | None = None


def needs_fix(text: str) -> bool:
    # Pure Latin-script text (English, Spanish, French...) has nothing to fix.
    return has_non_latin_script(text) or bool(ROMAN_HINDI.search(text))


def enabled() -> bool:
    return bool(settings.gemini_api_key and settings.normalize_model)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def looks_translated(raw: str, fixed: str) -> bool:
    """True if real Hindi in `raw` vanished from `fixed` (translated, not re-scripted).

    A phrase that is *entirely English* written in Devanagari ("आई डोंट नो") rightly
    becomes all-Latin, so we only object when genuine Hindi words were present."""
    hindi_words = len(HINDI_FUNCTION_WORDS.findall(raw))
    if hindi_words >= 2 and not HINDI_FUNCTION_WORDS.search(fixed) and not ROMAN_HINDI.search(fixed):
        return True
    return False


def _plausible(raw: str, fixed: str) -> bool:
    # Guard against the model answering/expanding instead of rewriting...
    if not fixed or not 0.5 <= len(fixed) / max(1, len(raw)) <= 1.6:
        return False
    # ...against translating Hindi into English...
    if looks_translated(raw, fixed):
        log.warning("normalize output looks translated; rejected")
        return False
    # ...and against introducing a script that wasn't spoken (e.g. Bengali letters
    # appearing in a Hindi phrase). Latin is always allowed (English words).
    new_scripts = set(detect_languages_by_script(fixed)) - set(detect_languages_by_script(raw)) - {"en"}
    if new_scripts:
        log.warning("normalize output added script(s) %s; rejected", sorted(new_scripts))
        return False
    return True


async def _ask(model: str, text: str) -> str | None:
    resp = await _get_client().aio.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(system_instruction=PROMPT, temperature=0),
    )
    return " ".join((resp.text or "").split()) or None


async def normalize_script(text: str) -> str | None:
    """Return the normalised text, or None if unchanged / unavailable.

    Hedged request: the primary model usually answers in ~0.7 s but sometimes stalls
    for 5 s+, so if it hasn't answered after HEDGE_AFTER seconds the backup model is
    asked too and the first good answer wins."""
    if not enabled() or not needs_fix(text):
        return None  # plain English -> nothing to fix
    models = [settings.normalize_model]
    if settings.normalize_backup_model and settings.normalize_backup_model not in models:
        models.append(settings.normalize_backup_model)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.normalize_timeout
    pending = {asyncio.create_task(_ask(models[0], text))}
    backups = models[1:]
    try:
        while pending:
            wait = deadline - loop.time()
            if backups:
                wait = min(wait, HEDGE_AFTER)
            if wait <= 0:
                break
            done, pending = await asyncio.wait(pending, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    fixed = task.result()
                except Exception as e:
                    log.warning("normalize call failed: %s", str(e)[:160])
                    continue
                if fixed and _plausible(text, fixed):
                    return fixed if fixed != text else None
            if backups and (not done or not pending):
                # primary slow (or failed) -> hedge with the backup model
                pending.add(asyncio.create_task(_ask(backups.pop(0), text)))
        log.warning("normalize: no usable answer in %.1fs; keeping raw text", settings.normalize_timeout)
        return None
    finally:
        for task in pending:
            task.cancel()

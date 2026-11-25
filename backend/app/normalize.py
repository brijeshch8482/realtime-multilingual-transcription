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
from .textutil import has_non_latin_script

log = logging.getLogger("normalize")

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


def _plausible(raw: str, fixed: str) -> bool:
    # Guard against the model answering/expanding instead of rewriting.
    return bool(fixed) and 0.5 <= len(fixed) / max(1, len(raw)) <= 1.6


async def normalize_script(text: str) -> str | None:
    """Return the normalised text, or None if unchanged / unavailable."""
    if not enabled() or not needs_fix(text):
        return None  # plain English -> nothing to fix
    try:
        resp = await asyncio.wait_for(
            _get_client().aio.models.generate_content(
                model=settings.normalize_model,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=PROMPT,
                    temperature=0,
                ),
            ),
            timeout=settings.normalize_timeout,
        )
        fixed = " ".join((resp.text or "").split())
        if fixed and fixed != text and _plausible(text, fixed):
            return fixed
    except asyncio.TimeoutError:
        log.warning("normalize timed out; keeping raw text")
    except Exception as e:
        log.warning("normalize failed: %s", e)
    return None

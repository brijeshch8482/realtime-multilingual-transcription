"""Language identification for saved transcripts.

Script ranges can't tell Spanish from English (both Latin) or Hindi from Marathi
(both Devanagari), so on save we ask a small Gemini model for the ISO 639-1
codes actually spoken, falling back to the offline script heuristic.
"""

import json
import logging
import re

from google import genai
from google.genai import types

from .config import settings
from .textutil import detect_languages_by_script

log = logging.getLogger("langdetect")

PROMPT = (
    "Identify every language used in this speech transcript, which may mix several "
    "languages (e.g. Hindi+English, Kannada+English, Spanish+English). English loanwords "
    "written in another script still count as English. Respond with a JSON array of "
    "ISO 639-1 codes ordered by how much each language is used, e.g. [\"kn\",\"en\"]."
)
_CODE = re.compile(r"^[a-z]{2,3}$")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=10_000),  # API minimum is 10s
        )
    return _client


def detect_languages(text: str) -> list[str]:
    fallback = detect_languages_by_script(text)
    if not (settings.gemini_api_key and settings.normalize_model):
        return fallback
    try:
        resp = _get_client().models.generate_content(
            model=settings.normalize_model,
            contents=text[:4000],
            config=types.GenerateContentConfig(
                system_instruction=PROMPT,
                temperature=0,
                response_mime_type="application/json",
                response_schema=list[str],
            ),
        )
        codes = []
        for c in json.loads(resp.text or "[]"):
            c = str(c).strip().lower()
            if _CODE.match(c) and c not in codes:
                codes.append(c)
        return codes[:6] or fallback
    except Exception as e:
        log.warning("language detection failed, using script fallback: %s", e)
        return fallback

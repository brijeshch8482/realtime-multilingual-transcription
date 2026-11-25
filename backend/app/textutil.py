import re

# Unicode script ranges -> most likely ISO 639-1 language. Used as a fast,
# offline fallback; the LLM-based detector (langdetect.py) refines it on save.
_SCRIPTS: list[tuple[str, str]] = [
    ("hi", r"ऀ-ॿ"),  # Devanagari (Hindi / Marathi / Nepali)
    ("bn", r"ঀ-৿"),  # Bengali / Assamese
    ("pa", r"਀-੿"),  # Gurmukhi
    ("gu", r"઀-૿"),  # Gujarati
    ("or", r"଀-୿"),  # Odia
    ("ta", r"஀-௿"),  # Tamil
    ("te", r"ఀ-౿"),  # Telugu
    ("kn", r"ಀ-೿"),  # Kannada
    ("ml", r"ഀ-ൿ"),  # Malayalam
    ("si", r"඀-෿"),  # Sinhala
    ("th", r"฀-๿"),  # Thai
    ("ar", r"؀-ۿݐ-ݿ"),  # Arabic script (Arabic / Urdu / Persian)
    ("he", r"֐-׿"),  # Hebrew
    ("ru", r"Ѐ-ӿ"),  # Cyrillic
    ("el", r"Ͱ-Ͽ"),  # Greek
    ("ja", r"぀-ヿ"),  # Hiragana / Katakana
    ("ko", r"가-힯ᄀ-ᇿ"),  # Hangul
    ("zh", r"一-鿿"),  # Han (Chinese, also used in Japanese)
]
_SCRIPT_RES = [(code, re.compile(f"[{rng}]")) for code, rng in _SCRIPTS]
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def detect_languages_by_script(text: str) -> list[str]:
    """Offline guess from the scripts present. Latin script is assumed English."""
    langs = [code for code, rx in _SCRIPT_RES if rx.search(text)]
    if "ja" in langs and "zh" in langs:
        langs.remove("zh")  # kana + kanji -> Japanese
    if _LATIN.search(text):
        langs.append("en")
    return langs


_NON_LATIN = re.compile("[" + "".join(rng for _, rng in _SCRIPTS) + "]")


def has_non_latin_script(text: str) -> bool:
    return bool(_NON_LATIN.search(text))


def non_latin_ratio(text: str) -> float:
    """Share of letters written in a non-Latin script (0..1)."""
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    return len(_NON_LATIN.findall(text)) / letters


def default_title(text: str, words: int = 6) -> str:
    parts = text.split()
    title = " ".join(parts[:words])
    if len(parts) > words:
        title += "…"
    return title[:200] or "Untitled"

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _normalize_db_url(url: str) -> str:
    # Hosts (Render, Neon, Heroku...) hand out postgres:// URLs; use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    # 2.5 native-audio streams the transcript word by word; 3.1 Flash Live only
    # returns it after each utterance ends (measured: ~0.3s vs ~7s per sentence).
    gemini_model: str = os.getenv(
        "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
    ).strip()
    # Small text model for script clean-up of live phrases and language ID on save.
    # Empty = disabled (raw Gemini Live output + offline script-based language tags).
    normalize_model: str = os.getenv("NORMALIZE_MODEL", "gemini-3.5-flash-lite").strip()
    normalize_backup_model: str = os.getenv("NORMALIZE_BACKUP_MODEL", "gemini-3.1-flash-lite").strip()
    normalize_timeout: float = float(os.getenv("NORMALIZE_TIMEOUT", "5"))
    # Accurate pass over the whole recording on Stop: "model[:thinking_level]" tried in
    # order (free-tier quotas are per model, and models are sometimes overloaded).
    # Empty = disabled (keep the live draft).
    final_models: list[tuple[str, str]] = [
        (m.split(":")[0].strip(), (m.split(":")[1] if ":" in m else "").strip())
        for m in os.getenv(
            "FINAL_MODELS",
            "gemini-3.5-flash:minimal,gemini-3.1-flash-lite,gemini-3.8-flash:low,gemini-3.7-flash:low",
        ).split(",")
        if m.strip()
    ]
    final_timeout: float = float(os.getenv("FINAL_TIMEOUT", "30"))
    gemini_api_version: str = os.getenv("GEMINI_API_VERSION", "v1alpha").strip()
    silence_ms: int = int(os.getenv("SILENCE_MS", "500"))
    database_url: str = _normalize_db_url(
        os.getenv("DATABASE_URL", "").strip()
        or f"sqlite:///{(BACKEND_DIR / 'transcriptions.db').as_posix()}"
    )
    # Built frontend served by FastAPI (single-service deploy). Missing = API only.
    static_dir: Path = Path(
        os.getenv("STATIC_DIR", "") or BACKEND_DIR.parent / "frontend" / "dist"
    )
    cors_origins: list[str] = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]


settings = Settings()

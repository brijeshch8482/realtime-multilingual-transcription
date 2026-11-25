import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers tables)
from .config import settings
from .db import Base, db_kind, engine
from .live import transcribe_ws
from .routers import transcriptions

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Speech to Text API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcriptions.router)


@app.middleware("http")
async def no_cache_html(request, call_next):
    # index.html must be revalidated so a redeploy is picked up immediately;
    # hashed /assets/* files stay cacheable.
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "gemini_configured": bool(settings.gemini_api_key),
        "model": settings.gemini_model,
        "database": db_kind(),
    }


@app.websocket("/ws/transcribe")
async def ws_transcribe(ws: WebSocket):
    await transcribe_ws(ws)


# Serve the built React app from the same origin (mounted last so API routes win).
if (settings.static_dir / "index.html").is_file():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")

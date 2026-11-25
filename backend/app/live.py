"""WebSocket proxy: browser PCM audio  ->  Gemini Live API  ->  live transcript.

Browser -> server
  * binary frames : raw PCM16 mono 16 kHz little-endian audio
  * text frame    : {"type": "stop"}  (flush and close)

Server -> browser (JSON)
  * {"type": "ready"}                    Gemini session open, start sending audio
  * {"type": "partial", "text": "..."}   current phrase, still changing
  * {"type": "final",   "id": n, "text": "..."}  phrase committed
  * {"type": "revise",  "id": n, "text": "..."}  phrase n with English words in Latin script
  * {"type": "speech",  "active": bool}  Gemini's voice-activity detection
  * {"type": "finalizing"}               after Stop: accurate pass over the recording
  * {"type": "final_transcript", "text": "...", "languages": [...]}
                                         replaces the live draft (skipped on failure)
  * {"type": "error",   "message": "..."}
  * {"type": "closed"}                   session finished
"""

import asyncio
import contextlib
import json
import logging
import os
import re

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from . import final_pass
from .config import settings
from .normalize import normalize_script

log = logging.getLogger("live")
DEBUG_RAW = os.getenv("LIVE_DEBUG", "") == "1"

SYSTEM_PROMPT = (
    "You are a silent transcription listener. The user is dictating; they are not "
    "talking to you. Never answer, comment or speak. Stay completely silent."
)

AUDIO_MIME = "audio/pcm;rate=16000"
IDLE_FINALIZE_SEC = 1.2  # commit a phrase if no new text arrives for this long
STOP_DRAIN_SEC = 2.5  # after Stop, wait this long for trailing transcription
REPLAY_BYTES = 3 * 2 * 16000  # on fallback to Gemini, replay the last 3 s of audio

LANGUAGE_CODES = [
    c.strip() for c in os.getenv("LANGUAGE_CODES", "").split(",") if c.strip()
]

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # The Live endpoint 404s on v1beta for newer (AQ.*) API keys; v1alpha works.
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(api_version=settings.gemini_api_version),
        )
    return _client


def _build_config(with_language_codes: bool) -> types.LiveConnectConfig:
    transcription = types.AudioTranscriptionConfig(
        language_codes=LANGUAGE_CODES if with_language_codes and LANGUAGE_CODES else None
    )
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=SYSTEM_PROMPT,
        input_audio_transcription=transcription,
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                prefix_padding_ms=200,
                silence_duration_ms=settings.silence_ms,
            )
        ),
    )


class _Transcript:
    """Tracks the phrase currently being spoken and commits it when done."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.committed = ""  # pieces from input_transcription (final-quality)
        self.interim = ""  # low-latency preview from interim_input_transcription
        self._idle_task: asyncio.Task | None = None
        self._seq = 0
        self._texts: dict = {}  # phrase id -> text (insertion order = spoken order)
        self._revisions: set[asyncio.Task] = set()

    async def _send(self, payload: dict):
        try:
            await self.ws.send_json(payload)
        except Exception:
            pass

    def draft(self) -> str:
        """Full live transcript so far, using the cleaned-up version of each phrase."""
        return " ".join(self._texts.values())

    def add_phrase(self, pid, text: str):
        """Browser mode: a phrase finalised by the browser's recogniser -> clean it up."""
        self._texts[pid] = text
        self._start_revision(pid, text)

    def _start_revision(self, pid, text: str):
        task = asyncio.create_task(self._revise(pid, text))
        self._revisions.add(task)
        task.add_done_callback(self._revisions.discard)

    def _current(self) -> str:
        # Prefer the longer view of the phrase so the preview never "shrinks".
        a, b = self.committed.strip(), self.interim.strip()
        return a if len(a) >= len(b) else b

    async def on_interim(self, text: str):
        prev = self.interim
        # Interim updates are usually cumulative; if a chunk is clearly a delta, append.
        if prev and len(text) < len(prev) and not text.startswith(prev[: max(1, len(prev) // 2)]):
            self.interim = prev + text
        else:
            self.interim = text
        await self._send({"type": "partial", "text": self._current()})
        self._arm_idle()

    async def on_final_piece(self, text: str, finished: bool):
        self.committed += text
        if finished:
            await self.flush()
        else:
            await self._send({"type": "partial", "text": self._current()})
            self._arm_idle()

    async def flush(self):
        if self._idle_task and self._idle_task is not asyncio.current_task():
            self._idle_task.cancel()
        self._idle_task = None
        text = " ".join(self._current().split())
        self.committed, self.interim = "", ""
        if text:
            self._seq += 1
            self._texts[self._seq] = text
            await self._send({"type": "final", "id": self._seq, "text": text})
            self._start_revision(self._seq, text)

    async def _revise(self, seq, text: str):
        fixed = await normalize_script(text)
        if fixed:
            self._texts[seq] = fixed
            await self._send({"type": "revise", "id": seq, "text": fixed})

    async def wait_revisions(self, timeout: float):
        if self._revisions:
            await asyncio.wait(set(self._revisions), timeout=timeout)

    def _arm_idle(self):
        if self._idle_task:
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_flush())

    async def _idle_flush(self):
        try:
            await asyncio.sleep(IDLE_FINALIZE_SEC)
            await self.flush()
        except asyncio.CancelledError:
            pass


async def _pump_results(session, transcript: _Transcript):
    while True:  # session.receive() ends after each model turn; keep listening
        async for msg in session.receive():
            if DEBUG_RAW:
                log.info("RAW %s", msg.model_dump(exclude_none=True, exclude={"data"}))
            va = getattr(msg, "voice_activity", None)
            if va is not None and va.voice_activity_type is not None:
                active = "START" in str(va.voice_activity_type)
                await transcript._send({"type": "speech", "active": active})
            sc = msg.server_content
            if sc is None:
                continue
            if sc.interim_input_transcription and sc.interim_input_transcription.text:
                await transcript.on_interim(sc.interim_input_transcription.text)
            if sc.input_transcription and (
                sc.input_transcription.text or sc.input_transcription.finished
            ):
                await transcript.on_final_piece(
                    sc.input_transcription.text or "", bool(sc.input_transcription.finished)
                )
            if sc.turn_complete or sc.interrupted:
                await transcript.flush()


async def _pump_audio(ws: WebSocket, session, recording: bytearray) -> bool:
    """Forward mic audio until the client sends stop (True) or disconnects (False)."""
    max_bytes = final_pass.MAX_SECONDS * 2 * final_pass.SAMPLE_RATE
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            return False
        if msg.get("bytes"):
            if len(recording) < max_bytes:
                recording.extend(msg["bytes"])  # kept for the accurate final pass
            await session.send_realtime_input(
                audio=types.Blob(data=msg["bytes"], mime_type=AUDIO_MIME)
            )
        elif msg.get("text"):
            try:
                data = json.loads(msg["text"])
            except ValueError:
                continue
            if data.get("type") == "stop":
                try:
                    await session.send_realtime_input(audio_stream_end=True)
                except Exception as e:  # older models may not support it
                    log.debug("audio_stream_end failed: %s", e)
                return True


async def _finish(ws: WebSocket, transcript: "_Transcript", recording: bytearray, lang: str | None):
    """After Stop: wait for phrase clean-ups, run the accurate pass, then close."""
    await transcript.wait_revisions(timeout=settings.normalize_timeout + 1)
    if final_pass.enabled():
        await ws.send_json({"type": "finalizing"})
        result = await final_pass.transcribe_recording(
            bytes(recording), draft=transcript.draft(), lang_hint=lang
        )
        if result:
            text, langs = result
            # Same script clean-up as live phrases (English words -> Latin)
            text = await normalize_script(text) or text
            await ws.send_json({"type": "final_transcript", "text": text, "languages": langs})
    await ws.send_json({"type": "closed"})


async def _run_session(ws: WebSocket, config: types.LiveConnectConfig, lang: str | None):
    """Gemini Live mode: Gemini produces the live text (auto language, ~2.5 s latency)."""
    client = _get_client()
    async with client.aio.live.connect(model=settings.gemini_model, config=config) as session:
        await ws.send_json({"type": "ready"})
        transcript = _Transcript(ws)
        recording = bytearray()
        results = asyncio.create_task(_pump_results(session, transcript))
        audio = asyncio.create_task(_pump_audio(ws, session, recording))
        try:
            done, _ = await asyncio.wait({results, audio}, return_when=asyncio.FIRST_COMPLETED)
            if results in done:  # Gemini side ended or failed
                results.result()  # re-raise if it failed
                return
            if audio.result():  # stopped by the user
                try:
                    await asyncio.wait_for(asyncio.shield(results), timeout=STOP_DRAIN_SEC)
                except asyncio.TimeoutError:
                    pass
                await transcript.flush()
                results.cancel()  # Live session no longer needed
                await _finish(ws, transcript, recording, lang)
        finally:
            for t in (results, audio):
                t.cancel()


async def _run_browser_mode(ws: WebSocket, lang: str | None):
    """Browser mode: the browser's own recogniser (Chrome Web Speech API) shows the live
    text with sub-second latency. The server cleans up each phrase's script, records the
    audio, and runs the accurate Gemini pass on Stop.

    If the browser's recogniser fails (e.g. Brave ships the API without Google's speech
    service, or the network blocks it), the client sends {"type": "use_gemini"} and this
    same session switches to Gemini Live for the live text - nothing recorded is lost."""
    await ws.send_json({"type": "ready"})
    transcript = _Transcript(ws)
    recording = bytearray()
    max_bytes = final_pass.MAX_SECONDS * 2 * final_pass.SAMPLE_RATE
    session = None
    results: asyncio.Task | None = None
    async with contextlib.AsyncExitStack() as stack:
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    if len(recording) < max_bytes:
                        recording.extend(msg["bytes"])
                    if session is not None:
                        await session.send_realtime_input(
                            audio=types.Blob(data=msg["bytes"], mime_type=AUDIO_MIME)
                        )
                    continue
                try:
                    data = json.loads(msg.get("text") or "")
                except ValueError:
                    continue
                kind = data.get("type")
                if kind == "phrase":
                    text = " ".join(str(data.get("text", "")).split())[:5000]
                    pid = str(data.get("id", ""))[:64]
                    if text and pid:
                        transcript.add_phrase(pid, text)
                elif kind == "use_gemini" and session is None:
                    try:
                        session = await stack.enter_async_context(
                            _get_client().aio.live.connect(
                                model=settings.gemini_model,
                                config=_build_config(with_language_codes=False),
                            )
                        )
                        results = asyncio.create_task(_pump_results(session, transcript))
                        await ws.send_json({"type": "mode", "mode": "gemini"})
                        # Replay the last few seconds so words spoken while the browser's
                        # recogniser was failing still show up live.
                        tail = bytes(recording[-REPLAY_BYTES:])
                        for i in range(0, len(tail), 3200):
                            await session.send_realtime_input(
                                audio=types.Blob(data=tail[i : i + 3200], mime_type=AUDIO_MIME)
                            )
                    except Exception as e:
                        log.warning("fallback to Gemini Live failed: %s", e)
                        await ws.send_json(
                            {"type": "error", "message": f"Live fallback failed: {e}"}
                        )
                elif kind == "stop":
                    if session is not None and results is not None:
                        try:
                            await session.send_realtime_input(audio_stream_end=True)
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(asyncio.shield(results), timeout=STOP_DRAIN_SEC)
                        except (asyncio.TimeoutError, Exception):
                            pass
                        await transcript.flush()
                    break
        finally:
            if results is not None:
                results.cancel()
    await _finish(ws, transcript, recording, lang)


_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,4}){0,2}$")


async def transcribe_ws(ws: WebSocket):
    await ws.accept()
    if not settings.gemini_api_key:
        await ws.send_json(
            {"type": "error", "message": "GEMINI_API_KEY is not set on the server (backend/.env)."}
        )
        await ws.close()
        return
    mode = ws.query_params.get("mode", "gemini")
    lang = ws.query_params.get("lang") or None
    if lang and not _LANG_RE.match(lang):
        lang = None
    try:
        if mode == "browser":
            await _run_browser_mode(ws, lang)
            return
        try:
            await _run_session(ws, _build_config(with_language_codes=True), lang)
        except WebSocketDisconnect:
            raise
        except Exception as e:
            # Some models reject language_codes; retry once without them before failing.
            if LANGUAGE_CODES and "language" in str(e).lower():
                log.warning("Retrying without language_codes: %s", e)
                await _run_session(ws, _build_config(with_language_codes=False), lang)
            else:
                raise
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("Live session failed")
        try:
            await ws.send_json({"type": "error", "message": f"Transcription error: {e}"})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

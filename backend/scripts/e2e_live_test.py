"""End-to-end test of the real-time pipeline, without a browser.

Synthesises a spoken Hinglish sentence (Microsoft neural TTS via edge-tts), converts
it to 16 kHz PCM16 exactly like the browser AudioWorklet does, streams it in real
time to the backend's /ws/transcribe WebSocket, and prints the live partial/final
events with timings.

    cd backend
    .venv\\Scripts\\python scripts\\e2e_live_test.py
    .venv\\Scripts\\python scripts\\e2e_live_test.py --text "..." --voice en-IN-NeerjaNeural --save
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.request

import edge_tts
import miniaudio
import websockets

DEFAULT_TEXTS = [
    "नमस्ते, मेरा नाम राहुल है और मैं आज की meeting के बारे में बात करना चाहता हूँ।",
    "कल हमारी project deadline है, so please make sure सारे reports submit हो जाएँ।",
    "Let's meet at five PM और फिर dinner के लिए चलेंगे।",
]
RATE = 16000
CHUNK_MS = 100


async def synthesize(text: str, voice: str) -> bytes:
    mp3 = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    decoded = miniaudio.decode(
        bytes(mp3), output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=RATE
    )
    return decoded.samples.tobytes()


async def stream(url: str, pcm: bytes, pause_sec: float) -> tuple[list[str], float]:
    chunk_bytes = RATE * 2 * CHUNK_MS // 1000
    silence = b"\x00" * chunk_bytes
    finals: list[str] = []
    ids: list = []
    t0 = time.perf_counter()
    first_partial = None

    def ts():
        return f"{time.perf_counter() - t0:6.2f}s"

    async with websockets.connect(url, max_size=None) as ws:
        msg = json.loads(await ws.recv())
        print(ts(), msg)
        if msg["type"] != "ready":
            raise SystemExit("Backend did not become ready")
        t0 = time.perf_counter()

        async def sender():
            for i in range(0, len(pcm), chunk_bytes):
                await ws.send(pcm[i : i + chunk_bytes])
                await asyncio.sleep(CHUNK_MS / 1000)  # real-time pacing
            for _ in range(int(pause_sec * 1000 / CHUNK_MS)):  # trailing silence
                await ws.send(silence)
                await asyncio.sleep(CHUNK_MS / 1000)
            print(ts(), "-> stop")
            await ws.send(json.dumps({"type": "stop"}))

        send_task = asyncio.create_task(sender())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "partial":
                    first_partial = first_partial or time.perf_counter() - t0
                    print(ts(), "partial:", msg["text"])
                elif msg["type"] == "final":
                    print(ts(), "FINAL:  ", msg["text"])
                    finals.append(msg["text"])
                    ids.append(msg.get("id"))
                elif msg["type"] == "revise":
                    print(ts(), "REVISE: ", msg["text"])
                    if msg.get("id") in ids:
                        finals[ids.index(msg["id"])] = msg["text"]
                elif msg["type"] == "speech":
                    print(ts(), "speech", "start" if msg["active"] else "end")
                elif msg["type"] == "final_transcript":
                    print(ts(), "ACCURATE:", msg["text"], msg.get("languages"))
                    finals[:] = [msg["text"]]  # replaces the live draft
                else:
                    print(ts(), msg)
                if msg["type"] in ("closed", "error"):
                    break
        finally:
            send_task.cancel()
    return finals, first_partial or -1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8000/ws/transcribe")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--voice", default="hi-IN-SwaraNeural")
    p.add_argument("--text", action="append", help="sentence(s) to speak; repeatable")
    p.add_argument("--pause", type=float, default=1.5, help="silence after the speech (s)")
    p.add_argument("--save", action="store_true", help="save the result via the REST API")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    texts = args.text or DEFAULT_TEXTS
    print("Synthesising speech…")
    gap = b"\x00" * (RATE * 2 * 800 // 1000)  # 0.8 s pause between sentences
    pcm = gap.join(asyncio.run(synthesize(t, args.voice)) for t in texts)
    print(f"Audio: {len(pcm) / 2 / RATE:.1f}s. Expected text:")
    for t in texts:
        print("   ", t)
    print()

    finals, first_partial = asyncio.run(stream(args.url, pcm, args.pause))
    full = " ".join(finals)
    print("\n=== RESULT ===")
    print("Transcript:", full or "(empty)")
    print(f"First text after: {first_partial:.2f}s" if first_partial >= 0 else "No partial text received")

    if args.save and full:
        req = urllib.request.Request(
            f"{args.api}/api/transcriptions",
            data=json.dumps({"title": "E2E test", "text": full, "duration_sec": round(len(pcm) / 2 / RATE)}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            print("Saved:", json.loads(r.read())["id"])
    sys.exit(0 if full else 1)


if __name__ == "__main__":
    main()

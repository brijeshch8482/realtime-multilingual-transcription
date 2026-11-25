# Speech to Text: Real-time Multilingual Transcription

**🔗 Live demo: https://speech-to-text-4c27.onrender.com**

Open it in **Google Chrome** or **Microsoft Edge**, allow the microphone, pick your language and click the mic. In other browsers (Firefox, Brave), live text uses Gemini and runs about 2.5 s behind your voice. The app is on Render's free plan, so the first visit after a while can take about a minute to wake up.

Speak in any language, or mix languages the way people actually talk: Hindi + English, Kannada + English, Tamil + English, Spanish + English, and so on. Words appear on screen **as you speak, typically under half a second behind your voice**. When you stop, the whole recording gets a second, more accurate pass. Transcripts are saved to PostgreSQL and managed from a dashboard with full CRUD, search and export.

## Architecture

```
 Browser (React + Vite)                     Backend (FastAPI, Python)                  Google
 ──────────────────────                     ─────────────────────────                  ──────
 ⚡ Instant mode (language picked):
 Chrome Web Speech API ─ interim words ~0.3-0.5 s ─► shown immediately                  (Google speech, in-browser)
   finalised phrase ──────────WS──────────► phrase script clean-up ──────────────►  3.5-flash-lite (text)

 Auto-detect mode (any language):
 Mic → AudioWorklet → PCM16 ─WS──────────► Gemini Live proxy ────────WS─────────►  Gemini Live API (~2.5 s lag)

 Both modes:
 Mic → AudioWorklet → PCM16 16 kHz ─WS───► recording buffer
 final_transcript ◄────────WS──────────── on Stop: whole recording ─────────────►  3.5-flash → fallbacks (audio)
                                                                                   accurate transcript + languages
 Dashboard ──REST──────────────────────► /api/transcriptions (CRUD, search, paging)
                                                   │
                                                   ▼
                                       PostgreSQL (SQLAlchemy) · SQLite fallback for dev
```

### How a recording flows
1. **Pick a language.** Choose the language you'll speak, which you can freely mix with English (Hindi, Kannada, Tamil, Telugu, Bengali, Marathi, Gujarati, Malayalam, Punjabi, Urdu, Spanish, French, Arabic, Chinese, Japanese, Korean…), or choose **Auto-detect**.
2. **Live text: instant mode (default).** Chrome's built-in recogniser (Web Speech API, Google's speech service) shows words **typically within half a second of speaking**, in grey. A phrase turns final when you pause.
3. **Live text: auto-detect mode.** Audio streams to a **Gemini Live** session that detects any language automatically. It is about 2.5 s behind speech; we measured this as the floor for every Gemini Live model, which is why instant mode exists. This mode is also used automatically in browsers without a working speech service: Firefox has no Web Speech API, and **Brave** exposes the API but ships without Google's speech service, so it always fails with a `network` error. If the browser's recogniser fails mid-session, the server switches that session to Gemini Live and replays the last 3 s of audio, so no words are lost.
4. **Script clean-up (per phrase).** Recognisers often write English words in the other language's script (`प्रोजेक्ट`, `ಮೀಟಿಂಗ್`) or romanise Hindi (`aur fir`). A fast text model rewrites each phrase so **English is in Latin script and every other language is in its own script**. Nothing is translated, and the phrase updates in place about 1 s later.
5. **Accurate pass (on Stop).** Mic audio is streamed to the server in both modes. On Stop, the whole recording is sent to a regular Gemini model, together with the live text and the chosen language as hints. The returned transcript replaces the live draft and comes with ISO language codes. If every model fails (quota or timeout), the live text is kept.
6. **Save.** The transcript is stored with its languages. Manually created or edited text gets its languages identified in a background task.

### Why these models (measured, not guessed)
| Choice | Reason |
|---|---|
| Instant live text: Chrome Web Speech API | Interim words typically within half a second. Every Gemini Live model measured **2.5–2.7 s** to the first word (`2.5-flash-native-audio` variants), and `3.1-flash-live` / `3.8-live` took about 7.8 s. None of them sent low-latency interim transcripts. |
| Auto-detect: `gemini-2.5-flash-native-audio-preview-12-2025` | The fastest Live model, and it streams word by word. It detects any language, but its language ID is fragile (Kannada sometimes came back as Burmese text, and Hindi flipped to Urdu script). The accurate pass fixes this on Stop. |
| Live API version `v1alpha` | Newer `AQ.*` API keys get HTTP 404 on the `v1beta` Live endpoint. |
| No `language_codes` hint | Testing showed the hints are ignored, and auto-detect handles any language. |
| Clean-up: `gemini-3.5-flash-lite` | Took 0.7 s at the median (0.84 s at most) and gave the best script fixes of the models tested. |
| Accurate pass: `3.5-flash` → `3.1-flash-lite` → `3.8-flash` → `3.7-flash` | `3.5-flash` was accurate on every Kannada and Tamil sample. Free-tier quotas are per model (`3.5-flash` allows only 20 requests a day), so the chain falls through on a 429 or 503. |

### Tested languages (spoken + English)
These were tested end-to-end with synthesised speech (`backend/scripts/e2e_live_test.py`): **Hindi, Kannada, Tamil, Telugu, Bengali, Marathi, Spanish**. The script map and prompts cover the other major scripts too: Gujarati, Punjabi, Malayalam, Odia, Urdu/Arabic, Thai, Cyrillic, Greek, Hebrew, Chinese, Japanese and Korean.

## Tech stack
| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite, AudioWorklet, plain CSS (light and dark) |
| Backend | Python 3.12, FastAPI, WebSockets, `google-genai` SDK |
| Database | PostgreSQL 16 + SQLAlchemy 2 (SQLite fallback for zero-setup dev) |
| Speech | Google Gemini Live API, plus Gemini text and audio models |
| Deploy | One Docker image (FastAPI serves the built frontend), with a Render blueprint |

## Run locally

**1. API key.** Get a free key at https://aistudio.google.com/apikey, then:
```bash
cp backend/.env.example backend/.env     # then set GEMINI_API_KEY=...
```

**Option A: Docker (app + PostgreSQL)**
```bash
docker compose up --build
```
Open http://localhost:8000.

**Option B: dev mode with hot reload**
```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```
With `DATABASE_URL` empty, the backend uses SQLite. To use Postgres in dev, run `docker compose up -d db` and set `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/transcriptions`.

Use Chrome or Edge. Mic access requires `localhost` or HTTPS.

### End-to-end test (no browser or mic needed)
```bash
cd backend
pip install -r requirements-dev.txt
python scripts/e2e_live_test.py                                   # Hinglish
python scripts/e2e_live_test.py --voice kn-IN-SapnaNeural \
    --text "ನಾಳೆ ನಮ್ಮ team meeting ಇದೆ, please time ಗೆ ಬನ್ನಿ."      # Kannada + English
```
The script synthesises speech with Microsoft neural voices, streams it in real time to `/ws/transcribe`, and prints every partial, final, revise and accurate event with timings.

## Deploy (Render, free tier)
1. Push this repo to GitHub.
2. In Render, go to **New → Blueprint** and select the repo. `render.yaml` creates the web service (Docker) and a PostgreSQL database.
3. Paste your `GEMINI_API_KEY` when asked, then click **Apply**.

Free Render services sleep after 15 minutes idle, so the first request takes about 1 minute to wake. Free Postgres expires after 30 days.

## API
| Method | Endpoint | Description |
|---|---|---|
| WS | `/ws/transcribe` | Binary PCM16 frames in. JSON events out: `ready`, `partial`, `final{id}`, `revise{id}`, `speech`, `finalizing`, `final_transcript{text,languages}`, `error`, `closed`. Send `{"type":"stop"}` to finish. |
| GET | `/api/transcriptions?q=&page=&page_size=` | List with search and pagination |
| GET | `/api/transcriptions/{id}` | Get one |
| POST | `/api/transcriptions` | Create `{title?, text, duration_sec?, languages?}` |
| PUT | `/api/transcriptions/{id}` | Update `{title?, text?}` |
| DELETE | `/api/transcriptions/{id}` | Delete |
| GET | `/api/health` | Shows whether Gemini is configured, plus the model and database in use |

Interactive docs: http://localhost:8000/docs

## Configuration (`backend/.env`)
| Var | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | (empty) | Required |
| `GEMINI_MODEL` | `gemini-2.5-flash-native-audio-preview-12-2025` | Live model |
| `GEMINI_API_VERSION` | `v1alpha` | Live endpoint version |
| `SILENCE_MS` | `500` | Pause length that ends a phrase |
| `NORMALIZE_MODEL` | `gemini-3.5-flash-lite` | Per-phrase script clean-up and language ID. Empty = off |
| `FINAL_MODELS` | `gemini-3.5-flash:minimal,gemini-3.1-flash-lite,...` | Accurate-pass chain, as `model[:thinking]`. Empty = off |
| `FINAL_TIMEOUT` | `30` | Total seconds allowed for the accurate pass |
| `DATABASE_URL` | SQLite | `postgres://` and `postgresql://` URLs are accepted |
| `LIVE_DEBUG` | (unset) | Set to `1` to log raw Gemini Live messages |

## Known limitations
- **Free-tier quotas.** `gemini-3.5-flash` allows 20 requests a day. After that, the accurate pass falls back to `3.1-flash-lite`, which is accurate but slower (5–15 s after Stop).
- **The accurate pass can still miss words.** The Tamil sample consistently lost "office-க்கு late" in every model tested.
- **Clean-up can fix words, not just scripts.** It sometimes repairs misheard words from context (for example, Kannada "ಆಫ್ ಸ್ಕಿಪ್" → "office"). This usually helps, but it is the model's guess.
- **Recording length.** Gemini Live audio sessions are capped at about 15 minutes. The accurate pass covers recordings up to 9 minutes; longer recordings keep the live draft.

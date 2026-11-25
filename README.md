# Speech to Text: Real-time Multilingual Transcription

Speak in any language, or mix languages the way people actually talk: Hindi + English, Kannada + English, Tamil + English, Spanish + English, and so on. Words appear on screen **live as you speak**. When you stop, the whole recording gets a second, more accurate pass. Transcripts are saved to PostgreSQL and managed from a dashboard with full CRUD, search and export.

## Architecture

```
 Browser (React + Vite)                 Backend (FastAPI, Python)                      Google Gemini
 ──────────────────────                 ─────────────────────────                      ─────────────
 Mic → AudioWorklet → PCM16 16 kHz ─WS─► /ws/transcribe proxy ─────────WS──────────►  Gemini Live API
                                         (API key never leaves server)                 (word-by-word draft)
 partial / final / revise  ◄──WS───────  per phrase: script clean-up ──────────────►  3.5-flash-lite (text)
 final_transcript          ◄──WS───────  on Stop: whole recording ─────────────────►  3.5-flash → fallbacks (audio)
                                                                                       accurate transcript + languages
 Dashboard ──REST──────────────────────► /api/transcriptions  (CRUD, search, paging)
                                         language ID in background ────────────────►  3.5-flash-lite (text)
                                                   │
                                                   ▼
                                            PostgreSQL (SQLAlchemy)  ·  SQLite fallback for dev
```

### How a recording flows
1. **Capture.** An AudioWorklet downsamples the mic to 16 kHz mono PCM16 and streams 100 ms chunks over a WebSocket.
2. **Live draft (pass 1).** The backend forwards audio to a **Gemini Live** session (`gemini-2.5-flash-native-audio`) with input transcription on. Words stream back about 0.3 s apart and appear in grey. A phrase is committed when the speaker pauses.
3. **Script clean-up (per phrase).** Gemini Live often writes English words in the other language's script (`प्रोजेक्ट`, `ಮೀಟಿಂಗ್`) or romanises Hindi (`aur fir`). A fast text model rewrites each committed phrase so **English is in Latin script and every other language is in its own script**. Nothing is translated. Each phrase updates in place about 0.7 s later.
4. **Accurate pass (pass 2, on Stop).** Gemini Live's automatic language ID is fragile for some languages; in testing, Kannada sometimes came back as Burmese text or as English-sounding words. When you press Stop, the full recording is sent to a regular Gemini model, along with the draft as a hint. The model returns an accurate transcript plus ISO language codes. This replaces the draft. If every model fails (quota or timeout), the draft is kept.
5. **Save.** The transcript is stored with its languages. Manually created or edited text gets its languages identified in a background task. The response returns instantly with a script-based guess.

### Why these models (measured, not guessed)
| Choice | Reason |
|---|---|
| Live: `gemini-2.5-flash-native-audio-preview-12-2025` | Streams the transcript word by word, with the first word about 2.5 s after speech starts. `gemini-3.1-flash-live-preview` returned each sentence only after it ended (about 7 s). |
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

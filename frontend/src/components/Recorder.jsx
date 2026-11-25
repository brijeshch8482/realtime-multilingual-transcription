import { useEffect, useRef, useState } from "react";
import { api, detectLanguages, formatDuration } from "../lib/api";
import { AUTO, INSTANT_LANGUAGES, instantSupported, loadLanguage, saveLanguage } from "../lib/languages";
import { useTranscriber } from "../lib/useTranscriber";
import LangBadges from "./LangBadges";

const STATUS_TEXT = {
  idle: "Ready",
  connecting: "Connecting…",
  listening: "Listening",
  stopping: "Finishing…",
  finalizing: "Improving accuracy…",
};

export default function Recorder({ onSaved, health }) {
  const t = useTranscriber();
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [lang, setLang] = useState(loadLanguage);
  const boxRef = useRef(null);

  const fullText = t.finals.map((f) => f.text).join(" ").trim();
  const live = t.status === "listening";
  const busy = t.status !== "idle";
  const hasResult = !busy && fullText.length > 0;
  const langs = t.languages || detectLanguages(fullText + " " + t.partial);
  const accurate = t.finals.length === 1 && t.finals[0].accurate;

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [t.finals, t.partial]);

  const onStart = () => {
    setSaved(null);
    setSaveError(null);
    setTitle("");
    t.start(lang);
  };

  const onLang = (e) => {
    setLang(e.target.value);
    saveLanguage(e.target.value);
  };

  const onSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const item = await api.create({
        title: title.trim() || null,
        text: fullText,
        duration_sec: Math.round(t.elapsed),
        languages: t.languages || undefined,
      });
      setSaved(item);
      t.reset();
      onSaved?.(item);
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const meter = Math.min(1, t.level * 6);

  return (
    <section className="card recorder">
      {health && !health.gemini_configured && (
        <div className="alert alert-warn">
          Gemini API key is not configured. Add <code>GEMINI_API_KEY</code> to <code>backend/.env</code> and restart the backend.
        </div>
      )}

      <div className="rec-top">
        <button
          className={`mic-btn ${live ? "mic-live" : ""}`}
          onClick={busy ? t.stop : onStart}
          disabled={t.status === "connecting" || t.status === "stopping" || t.status === "finalizing"}
          aria-label={busy ? "Stop recording" : "Start recording"}
          style={{ "--level": meter }}
        >
          {busy ? <span className="stop-icon" /> : <MicIcon />}
        </button>
        <div className="rec-meta">
          <div className={`status status-${t.status}`}>
            <span className="dot" /> {STATUS_TEXT[t.status]}
            {t.status === "listening" && t.speaking && <span className="speaking">· speech detected</span>}
          </div>
          <div className="timer">{formatDuration(t.elapsed)}</div>
          <div className="hint">
            {busy
              ? t.mode === "instant"
                ? "Speak naturally, mixing English in as you like. Click to stop."
                : "Speak in any language. Auto-detect shows words ~2.5 s after you say them. Click to stop."
              : "Pick your language, click the mic and start speaking."}
          </div>
        </div>
        <div className="rec-langs">
          <LangBadges langs={langs} />
        </div>
      </div>

      <div className="lang-row">
        <label htmlFor="lang">Language</label>
        <select id="lang" className="input select" value={lang} onChange={onLang} disabled={busy}>
          <optgroup label={instantSupported ? "⚡ Instant (pick the language you'll speak)" : "Instant mode needs Chrome or Edge"}>
            {INSTANT_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code} disabled={!instantSupported}>
                {l.label}
              </option>
            ))}
          </optgroup>
          <optgroup label="Any language">
            <option value={AUTO}>Auto-detect any language (slower, ~2.5 s delay)</option>
          </optgroup>
        </select>
      </div>

      {t.error && <div className="alert alert-error">{t.error}</div>}

      <div className="transcript" ref={boxRef} aria-live="polite">
        {!fullText && !t.partial && (
          <p className="placeholder">
            {busy ? "Listening… your words will appear here." : "Your live transcript will appear here."}
          </p>
        )}
        {t.finals.map((f) => (
          <span key={f.id} className={`final ${f.revised ? "revised" : ""}`}>{f.text} </span>
        ))}
        {t.partial && <span className="partial">{t.partial}</span>}
      </div>

      {t.status === "finalizing" && (
        <div className="note">Re-checking the full recording for the most accurate transcript…</div>
      )}
      {accurate && !busy && (
        <div className="note note-ok">✓ Accurate transcript from the full recording (replaced the live draft)</div>
      )}

      {hasResult && (
        <div className="save-row">
          <input
            className="input"
            placeholder="Title (optional — first words are used otherwise)"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button className="btn btn-primary" onClick={onSave} disabled={saving}>
            {saving ? "Saving…" : "Save to history"}
          </button>
          <button className="btn" onClick={t.reset} disabled={saving}>Discard</button>
        </div>
      )}
      {saveError && <div className="alert alert-error">Could not save: {saveError}</div>}
      {saved && (
        <div className="alert alert-ok">
          Saved “{saved.title}”. You'll find it in History.
        </div>
      )}
    </section>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <path d="M12 18v4" />
    </svg>
  );
}

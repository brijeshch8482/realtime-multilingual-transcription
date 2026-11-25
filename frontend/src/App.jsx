import { useEffect, useState } from "react";
import Dashboard from "./components/Dashboard";
import Recorder from "./components/Recorder";
import { api } from "./lib/api";

export default function App() {
  const [tab, setTab] = useState("record");
  const [refreshKey, setRefreshKey] = useState(0);
  const [health, setHealth] = useState(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setBackendDown(true));
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">🎙️</span>
          <div>
            <h1>Speech to Text</h1>
            <p className="muted">Real-time multilingual transcription · mix English with Hindi, Kannada, Tamil, Spanish…</p>
          </div>
        </div>
        <nav className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "record"} className={tab === "record" ? "active" : ""} onClick={() => setTab("record")}>
            Record
          </button>
          <button role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
            History
          </button>
        </nav>
      </header>

      {backendDown && (
        <div className="alert alert-error">
          Can't reach the backend at <code>/api</code>. Start it with <code>uvicorn app.main:app --reload</code> in the <code>backend</code> folder.
        </div>
      )}

      <main>
        {/* Recorder stays mounted so a recording keeps running while you browse history */}
        <div hidden={tab !== "record"}>
          <Recorder health={health} onSaved={() => setRefreshKey((k) => k + 1)} />
        </div>
        {tab === "history" && <Dashboard refreshKey={refreshKey} />}
      </main>

      <footer className="footer muted">
        Powered by Gemini Live API{health?.model ? ` · ${health.model}` : ""}{health?.database ? ` · ${health.database}` : ""}
      </footer>
    </div>
  );
}

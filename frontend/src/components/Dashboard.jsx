import { useCallback, useEffect, useState } from "react";
import { api, downloadText, formatDuration, parseDate } from "../lib/api";
import LangBadges from "./LangBadges";
import Modal from "./Modal";

const PAGE_SIZE = 8;

export default function Dashboard({ refreshKey }) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null); // item | {} for new
  const [viewing, setViewing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    const id = setTimeout(() => { setDebounced(query); setPage(1); }, 300);
    return () => clearTimeout(id);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.list({ q: debounced, page, pageSize: PAGE_SIZE });
      if (res.items.length === 0 && page > 1 && res.total > 0) {
        setPage((p) => p - 1);
        return;
      }
      setData(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [debounced, page]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const flash = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2200);
  };

  const copy = async (item) => {
    try {
      await navigator.clipboard.writeText(item.text);
      flash("Copied to clipboard");
    } catch {
      flash("Copy failed");
    }
  };

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  return (
    <section className="card">
      <div className="dash-head">
        <div>
          <h2>Transcription history</h2>
          <p className="muted">{data.total} saved {data.total === 1 ? "transcription" : "transcriptions"}</p>
        </div>
        <div className="dash-tools">
          <input
            className="input search"
            type="search"
            placeholder="Search title or text…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn btn-primary" onClick={() => setEditing({})}>+ New</button>
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          Could not load history: {error} <button className="link" onClick={load}>Retry</button>
        </div>
      )}

      {!error && !loading && data.items.length === 0 && (
        <div className="empty">
          {debounced ? `No transcriptions match “${debounced}”.` : "No transcriptions yet. Record one from the Record tab."}
        </div>
      )}

      <ul className={`list ${loading ? "is-loading" : ""}`}>
        {data.items.map((item) => (
          <li key={item.id} className="row">
            <button className="row-main" onClick={() => setViewing(item)}>
              <div className="row-title">
                <span>{item.title}</span>
                <LangBadges langs={item.languages} />
              </div>
              <p className="row-text">{item.text}</p>
              <div className="row-meta">
                {parseDate(item.created_at).toLocaleString()}
                {item.duration_sec > 0 && <> · {formatDuration(item.duration_sec)}</>}
                {parseDate(item.updated_at) - parseDate(item.created_at) > 1000 && <> · edited</>}
              </div>
            </button>
            <div className="row-actions">
              <button className="btn btn-sm" onClick={() => setEditing(item)}>Edit</button>
              <button className="btn btn-sm" onClick={() => copy(item)}>Copy</button>
              <button className="btn btn-sm" onClick={() => downloadText(item.title, item.text)}>Export</button>
              <button className="btn btn-sm btn-danger" onClick={() => setDeleting(item)}>Delete</button>
            </div>
          </li>
        ))}
      </ul>

      {pages > 1 && (
        <div className="pager">
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
          <span className="muted">Page {page} of {pages}</span>
          <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      )}

      {viewing && (
        <Modal
          title={viewing.title}
          wide
          onClose={() => setViewing(null)}
          footer={
            <>
              <button className="btn" onClick={() => copy(viewing)}>Copy</button>
              <button className="btn btn-primary" onClick={() => { setEditing(viewing); setViewing(null); }}>Edit</button>
            </>
          }
        >
          <div className="view-meta">
            <LangBadges langs={viewing.languages} />
            <span className="muted">{parseDate(viewing.created_at).toLocaleString()}</span>
          </div>
          <p className="view-text">{viewing.text}</p>
        </Modal>
      )}

      {editing && (
        <EditModal
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={(isNew) => {
            setEditing(null);
            flash(isNew ? "Transcription created" : "Changes saved");
            load();
          }}
        />
      )}

      {deleting && (
        <DeleteModal
          item={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            flash("Transcription deleted");
            load();
          }}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </section>
  );
}

function EditModal({ item, onClose, onSaved }) {
  const isNew = !item.id;
  const [title, setTitle] = useState(item.title || "");
  const [text, setText] = useState(item.text || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e?.preventDefault();
    if (!text.trim()) return setError("Text cannot be empty.");
    setBusy(true);
    setError(null);
    try {
      if (isNew) await api.create({ title: title.trim() || null, text });
      else await api.update(item.id, { title: title.trim() || item.title, text });
      onSaved(isNew);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={isNew ? "New transcription" : "Edit transcription"}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? "Saving…" : isNew ? "Create" : "Save changes"}
          </button>
        </>
      }
    >
      <form className="form" onSubmit={submit}>
        <label>
          Title
          <input className="input" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="Optional" />
        </label>
        <label>
          Text
          <textarea className="input textarea" value={text} onChange={(e) => setText(e.target.value)} rows={8} autoFocus />
        </label>
        {error && <div className="alert alert-error">{error}</div>}
      </form>
    </Modal>
  );
}

function DeleteModal({ item, onClose, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const confirm = async () => {
    setBusy(true);
    try {
      await api.remove(item.id);
      onDeleted();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Delete transcription?"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-danger-solid" onClick={confirm} disabled={busy}>
            {busy ? "Deleting…" : "Delete"}
          </button>
        </>
      }
    >
      <p>“{item.title}” will be permanently deleted. This can't be undone.</p>
      {error && <div className="alert alert-error">{error}</div>}
    </Modal>
  );
}

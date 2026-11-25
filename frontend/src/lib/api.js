// In dev, Vite proxies /api and /ws to the backend. For a separate deployment
// set VITE_API_URL (e.g. https://my-backend.onrender.com).
const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export function wsUrl(path) {
  if (API_BASE) return API_BASE.replace(/^http/, "ws") + path;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}${path}`;
}

async function request(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => request("/api/health"),
  list: ({ q = "", page = 1, pageSize = 10 } = {}) =>
    request(`/api/transcriptions?${new URLSearchParams({ q, page, page_size: pageSize })}`),
  get: (id) => request(`/api/transcriptions/${id}`),
  create: (data) => request("/api/transcriptions", { method: "POST", body: JSON.stringify(data) }),
  update: (id, data) =>
    request(`/api/transcriptions/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  remove: (id) => request(`/api/transcriptions/${id}`, { method: "DELETE" }),
};

// SQLite returns timestamps without a timezone; they are UTC.
export function parseDate(s) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
}

export function formatDuration(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Fast script-based guess for the live view (the backend refines it on save).
const SCRIPTS = [
  ["hi", /[ऀ-ॿ]/], // Devanagari
  ["bn", /[ঀ-৿]/], // Bengali
  ["pa", /[਀-੿]/], // Gurmukhi
  ["gu", /[઀-૿]/], // Gujarati
  ["or", /[଀-୿]/], // Odia
  ["ta", /[஀-௿]/], // Tamil
  ["te", /[ఀ-౿]/], // Telugu
  ["kn", /[ಀ-೿]/], // Kannada
  ["ml", /[ഀ-ൿ]/], // Malayalam
  ["si", /[඀-෿]/], // Sinhala
  ["th", /[฀-๿]/], // Thai
  ["ar", /[؀-ۿ]/], // Arabic script
  ["he", /[֐-׿]/], // Hebrew
  ["ru", /[Ѐ-ӿ]/], // Cyrillic
  ["el", /[Ͱ-Ͽ]/], // Greek
  ["ja", /[぀-ヿ]/], // Hiragana / Katakana
  ["ko", /[가-힯]/], // Hangul
  ["zh", /[一-鿿]/], // Han
];

export function detectLanguages(text) {
  let langs = SCRIPTS.filter(([, rx]) => rx.test(text)).map(([code]) => code);
  if (langs.includes("ja")) langs = langs.filter((l) => l !== "zh"); // kana + kanji = Japanese
  if (/[A-Za-zÀ-ɏ]/.test(text)) langs.push("en");
  return langs;
}

export function downloadText(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.replace(/[\\/:*?"<>|]+/g, "_") + ".txt";
  a.click();
  URL.revokeObjectURL(url);
}

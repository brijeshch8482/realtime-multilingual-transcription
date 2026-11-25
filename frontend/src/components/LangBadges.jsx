let names;
try {
  names = new Intl.DisplayNames(["en"], { type: "language" });
} catch {
  names = null;
}

export function languageName(code) {
  try {
    return names?.of(code) || code;
  } catch {
    return code;
  }
}

// Stable colour per language code (6 hues that read well in light + dark).
function hue(code) {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % 6;
}

export default function LangBadges({ langs }) {
  if (!langs?.length) return null;
  return (
    <span className="badges">
      {langs.map((l) => (
        <span key={l} className={`badge badge-c${l === "en" ? "en" : hue(l)}`} title={languageName(l)}>
          {l.toUpperCase()}
        </span>
      ))}
    </span>
  );
}

// Languages for the instant (browser recogniser) mode. Each is typically mixed with
// English while speaking; codes are BCP-47 tags understood by Chrome's Web Speech API.
export const INSTANT_LANGUAGES = [
  { code: "hi-IN", label: "Hindi + English" },
  { code: "kn-IN", label: "Kannada + English" },
  { code: "ta-IN", label: "Tamil + English" },
  { code: "te-IN", label: "Telugu + English" },
  { code: "bn-IN", label: "Bengali + English" },
  { code: "mr-IN", label: "Marathi + English" },
  { code: "gu-IN", label: "Gujarati + English" },
  { code: "ml-IN", label: "Malayalam + English" },
  { code: "pa-Guru-IN", label: "Punjabi + English" },
  { code: "ur-IN", label: "Urdu + English" },
  { code: "en-IN", label: "English (India)" },
  { code: "en-US", label: "English (US)" },
  { code: "es-ES", label: "Spanish + English" },
  { code: "fr-FR", label: "French + English" },
  { code: "de-DE", label: "German + English" },
  { code: "ar-SA", label: "Arabic + English" },
  { code: "cmn-Hans-CN", label: "Chinese (Mandarin) + English" },
  { code: "ja-JP", label: "Japanese + English" },
  { code: "ko-KR", label: "Korean + English" },
];

export const AUTO = "auto";

const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
export const SpeechRecognitionImpl = SR || null;

const KEY = "stt.language";
const BROKEN_KEY = "stt.instantBroken";

// Brave (and some other Chromium browsers) expose the API but ship without Google's
// speech service, so recognition always fails with a "network" error.
export const isBrave = typeof navigator !== "undefined" && !!navigator.brave;

function instantMarkedBroken() {
  try {
    return localStorage.getItem(BROKEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function markInstantBroken() {
  try {
    localStorage.setItem(BROKEN_KEY, "1");
  } catch {}
}

export const instantSupported = !!SR && !isBrave && !instantMarkedBroken();

export function instantUnavailableReason() {
  if (!SR) return "This browser has no built-in speech recognition.";
  if (isBrave) return "Brave doesn't include Google's speech service.";
  if (instantMarkedBroken()) return "This browser's speech service didn't respond last time.";
  return null;
}

export function loadLanguage() {
  try {
    const v = localStorage.getItem(KEY);
    if (v === AUTO || INSTANT_LANGUAGES.some((l) => l.code === v)) {
      return v === AUTO || instantSupported ? v : AUTO;
    }
  } catch {}
  return instantSupported ? "hi-IN" : AUTO;
}

export function saveLanguage(code) {
  try {
    localStorage.setItem(KEY, code);
  } catch {}
}

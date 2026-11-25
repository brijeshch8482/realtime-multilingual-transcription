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
export const instantSupported = !!SR;

const KEY = "stt.language";

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

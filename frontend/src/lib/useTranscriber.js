import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";
import { AUTO, SpeechRecognitionImpl } from "./languages";

// Two live modes, same accurate pass at the end:
//  * instant (language chosen): Chrome's own recogniser (Web Speech API, Google) shows
//    words ~0.3-0.5 s after they're spoken; the server cleans up each phrase's script.
//  * auto: Gemini Live detects any language but lags ~2.5 s behind speech.
// In both, mic audio is streamed to the server, and on Stop the whole recording is
// re-transcribed by Gemini for the most accurate result.
//
// status: idle | connecting | listening | stopping | finalizing
export function useTranscriber() {
  const [status, setStatus] = useState("idle");
  const [finals, setFinals] = useState([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState(null);
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [languages, setLanguages] = useState(null); // from the accurate final pass
  const [mode, setMode] = useState(null); // "instant" | "auto"

  const r = useRef({}); // ws, ctx, stream, node, timer, startedAt, ready, rec, ...

  const stopRecognition = useCallback(() => {
    const s = r.current;
    s.recActive = false;
    if (s.rec) {
      s.rec.onresult = s.rec.onerror = s.rec.onend = s.rec.onspeechstart = s.rec.onspeechend = null;
      try { s.rec.abort(); } catch {}
      s.rec = null;
    }
  }, []);

  const releaseAudio = useCallback(() => {
    const s = r.current;
    s.node?.port && (s.node.port.onmessage = null);
    try { s.node?.disconnect(); } catch {}
    s.stream?.getTracks().forEach((t) => t.stop());
    s.ctx?.state !== "closed" && s.ctx?.close().catch(() => {});
    clearInterval(s.timer);
    Object.assign(s, { node: null, stream: null, ctx: null, timer: null });
    setLevel(0);
  }, []);

  const teardown = useCallback(() => {
    const s = r.current;
    stopRecognition();
    releaseAudio();
    clearTimeout(s.stopTimeout);
    if (s.ws) {
      s.ws.onmessage = s.ws.onclose = s.ws.onerror = null;
      if (s.ws.readyState <= 1) s.ws.close();
      s.ws = null;
    }
    s.ready = false;
    const leftover = s.partial?.trim(); // keep any unflushed text
    if (leftover) setFinals((f) => [...f, { id: `local-${Date.now()}`, text: leftover }]);
    s.partial = "";
    setPartial("");
    setSpeaking(false);
    setStatus("idle");
  }, [releaseAudio, stopRecognition]);

  useEffect(() => teardown, [teardown]);

  // ---- instant mode: browser speech recognition -------------------------------------
  const commitPhrase = useCallback((text) => {
    const s = r.current;
    text = text.trim();
    if (!text) return;
    const id = `b${++s.seq}`;
    setFinals((f) => [...f, { id, text }]);
    if (s.ws?.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({ type: "phrase", id, text }));
  }, []);

  const startRecognition = useCallback(
    (lang) => {
      const s = r.current;
      const rec = new SpeechRecognitionImpl();
      rec.lang = lang;
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          const text = res[0]?.transcript || "";
          if (res.isFinal) commitPhrase(text);
          else interim += text;
        }
        s.partial = interim.trim();
        setPartial(s.partial);
      };
      rec.onspeechstart = () => setSpeaking(true);
      rec.onspeechend = () => setSpeaking(false);
      rec.onerror = (e) => {
        if (e.error === "no-speech" || e.error === "aborted") return;
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          s.recActive = false;
          setError("The browser blocked live speech recognition. Allow the microphone, or choose “Auto-detect” as the language.");
        } else if (e.error === "language-not-supported") {
          s.recActive = false;
          setError("This browser can't recognise the selected language live. Choose “Auto-detect” instead; you'll still get an accurate transcript on Stop.");
        } else if (e.error === "network") {
          setError("Live recognition lost its connection. Keep speaking: the accurate transcript is still produced when you stop.");
        }
      };
      rec.onend = () => {
        // Chrome ends a session after a pause or ~60 s; keep it running while recording.
        if (s.recActive) {
          const now = Date.now();
          s.recRestarts = (s.recRestarts || []).filter((t) => now - t < 3000).concat(now);
          if (s.recRestarts.length > 5) {
            s.recActive = false; // restarting in a tight loop -> give up
            return;
          }
          try { rec.start(); } catch {}
        } else {
          s.recEnded?.();
        }
      };
      s.rec = rec;
      s.recActive = true;
      s.recRestarts = [];
      try {
        rec.start();
      } catch (e) {
        setError(`Live recognition could not start: ${e?.message || e}`);
      }
    },
    [commitPhrase]
  );

  // ---- start / stop -------------------------------------------------------------------
  const start = useCallback(
    async (lang = AUTO) => {
      if (r.current.ws) return;
      const instant = lang !== AUTO && !!SpeechRecognitionImpl;
      setError(null);
      const s = r.current;
      s.partial = "";
      s.seq = 0;
      setMode(instant ? "instant" : "auto");
      setLanguages(null);
      setFinals([]);
      setPartial("");
      setElapsed(0);
      setStatus("connecting");
      try {
        s.stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        s.ctx = new AudioContext();
        await s.ctx.audioWorklet.addModule("/pcm-worklet.js");
        const source = s.ctx.createMediaStreamSource(s.stream);
        s.node = new AudioWorkletNode(s.ctx, "pcm-worklet", { processorOptions: { targetRate: 16000 } });
        const mute = s.ctx.createGain();
        mute.gain.value = 0; // keep the graph pulling audio without playing it back
        source.connect(s.node).connect(mute).connect(s.ctx.destination);
        s.node.port.onmessage = (e) => {
          setLevel(e.data.rms);
          if (s.ready && s.ws?.readyState === WebSocket.OPEN) s.ws.send(e.data.pcm);
        };
      } catch (e) {
        releaseAudio();
        setStatus("idle");
        setError(
          e?.name === "NotAllowedError"
            ? "Microphone permission was denied. Allow mic access in the browser and try again."
            : `Could not start microphone: ${e?.message || e}`
        );
        return;
      }

      const params = new URLSearchParams({ mode: instant ? "browser" : "gemini" });
      if (lang !== AUTO) params.set("lang", lang);
      const ws = new WebSocket(wsUrl(`/ws/transcribe?${params}`));
      ws.binaryType = "arraybuffer";
      s.ws = ws;
      ws.onmessage = (e) => {
        let msg;
        try { msg = JSON.parse(e.data); } catch { return; }
        if (msg.type === "ready") {
          if (!s.ready) {
            s.ready = true;
            s.startedAt = Date.now();
            s.timer = setInterval(() => setElapsed((Date.now() - s.startedAt) / 1000), 250);
            setStatus("listening");
            if (instant) startRecognition(lang);
          }
        } else if (msg.type === "partial") {
          s.partial = msg.text;
          setPartial(msg.text);
        } else if (msg.type === "final") {
          setFinals((f) => [...f, { id: msg.id, text: msg.text }]);
          s.partial = "";
          setPartial("");
        } else if (msg.type === "revise") {
          // Same phrase with scripts fixed (English words in Latin, etc.)
          setFinals((f) => f.map((x) => (x.id === msg.id ? { ...x, text: msg.text, revised: true } : x)));
        } else if (msg.type === "finalizing") {
          setStatus("finalizing");
          clearTimeout(s.stopTimeout);
          s.stopTimeout = setTimeout(teardown, 60000); // accurate pass can take a while
        } else if (msg.type === "final_transcript") {
          // Accurate transcript of the whole recording replaces the live draft
          setFinals([{ id: "final", text: msg.text, accurate: true }]);
          setLanguages(msg.languages?.length ? msg.languages : null);
        } else if (msg.type === "speech") {
          setSpeaking(msg.active);
        } else if (msg.type === "error") {
          setError(msg.message);
        } else if (msg.type === "closed") {
          teardown();
        }
      };
      ws.onerror = () => setError("Connection to the transcription server failed. Is the backend running?");
      ws.onclose = () => teardown();
    },
    [releaseAudio, startRecognition, teardown]
  );

  const stop = useCallback(async () => {
    const s = r.current;
    if (!s.ws) return;
    if (s.startedAt) setElapsed((Date.now() - s.startedAt) / 1000);
    setStatus("stopping");
    if (s.rec) {
      // Let the recogniser deliver its last result before closing the session.
      s.recActive = false;
      await new Promise((resolve) => {
        s.recEnded = resolve;
        try { s.rec.stop(); } catch { resolve(); }
        setTimeout(resolve, 1500);
      });
      s.recEnded = null;
      if (s.partial) {
        commitPhrase(s.partial);
        s.partial = "";
        setPartial("");
      }
      stopRecognition();
    }
    releaseAudio(); // mic off
    if (s.ws?.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({ type: "stop" }));
    clearTimeout(s.stopTimeout);
    s.stopTimeout = setTimeout(teardown, 8000); // safety net if server never replies
  }, [commitPhrase, releaseAudio, stopRecognition, teardown]);

  const reset = useCallback(() => {
    setLanguages(null);
    setFinals([]);
    setPartial("");
    setElapsed(0);
    setError(null);
  }, []);

  return { status, finals, partial, error, level, elapsed, speaking, languages, mode, start, stop, reset };
}

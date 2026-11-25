import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";

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

  const r = useRef({}); // ws, ctx, stream, node, timer, startedAt, ready, stopTimeout

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
  }, [releaseAudio]);

  useEffect(() => teardown, [teardown]);

  const start = useCallback(async () => {
    if (r.current.ws) return;
    setError(null);
    const s = r.current;
    s.partial = "";
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

    const ws = new WebSocket(wsUrl("/ws/transcribe"));
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
        }
      } else if (msg.type === "partial") {
        s.partial = msg.text;
        setPartial(msg.text);
      } else if (msg.type === "final") {
        setFinals((f) => [...f, { id: msg.id, text: msg.text }]);
        s.partial = "";
        setPartial("");
      } else if (msg.type === "revise") {
        // Same phrase with English words rewritten in Latin script
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
  }, [releaseAudio, teardown]);

  const stop = useCallback(() => {
    const s = r.current;
    if (!s.ws) return;
    if (s.startedAt) setElapsed((Date.now() - s.startedAt) / 1000);
    releaseAudio(); // mic off immediately
    setStatus("stopping");
    if (s.ws.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({ type: "stop" }));
    s.stopTimeout = setTimeout(teardown, 6000); // safety net if server never replies
  }, [releaseAudio, teardown]);

  const reset = useCallback(() => {
    setLanguages(null);
    setFinals([]);
    setPartial("");
    setElapsed(0);
    setError(null);
  }, []);

  return { status, finals, partial, error, level, elapsed, speaking, languages, start, stop, reset };
}

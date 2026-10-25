import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type InterviewSocket } from "../api/client";
import { errorMessage } from "../api/errors";
import type { InterviewClientMessage, InterviewServerMessage } from "../api/types";

// Contract section 9: the browser talks to the agents service over the WebSocket the backend
// hands out (POST /api/events/{id}/interview -> ws_url + interview_token).

type Role = "interviewer" | "user";
type Line = { role: Role; text: string };
type Phase = "idle" | "connecting" | "live" | "ending" | "done" | "error";

const MIC_RATE = 16000; // client -> server PCM16 mono
const SPEAKER_RATE = 24000; // server -> client PCM16 mono
const CHUNK_SAMPLES = MIC_RATE / 10; // ~100 ms

function toBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function fromBase64(data: string): Uint8Array {
  const bin = atob(data);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Mic capture -> PCM16 @ 16 kHz in ~100 ms chunks, plus 24 kHz playback with barge-in. */
class AudioIO {
  private ctx: AudioContext;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private pending: number[] = [];
  private playAt = 0;
  private sources = new Set<AudioBufferSourceNode>();

  constructor() {
    this.ctx = new AudioContext();
  }

  async startMic(onChunk: (base64: string) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const source = this.ctx.createMediaStreamSource(this.stream);
    // ScriptProcessorNode is deprecated but needs no separate worklet module; fine for a demo.
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const ratio = this.ctx.sampleRate / MIC_RATE;
    this.processor.onaudioprocess = (ev) => {
      const input = ev.inputBuffer.getChannelData(0);
      for (let i = 0; i < input.length / ratio; i++) {
        // Average the source samples that fall into this output sample (simple low-pass).
        const start = Math.floor(i * ratio);
        const end = Math.min(input.length, Math.floor((i + 1) * ratio));
        let sum = 0;
        for (let j = start; j < end; j++) sum += input[j];
        const v = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
        this.pending.push(v < 0 ? v * 0x8000 : v * 0x7fff);
      }
      while (this.pending.length >= CHUNK_SAMPLES) {
        const chunk = Int16Array.from(this.pending.splice(0, CHUNK_SAMPLES));
        onChunk(toBase64(new Uint8Array(chunk.buffer)));
      }
    };
    const mute = this.ctx.createGain();
    mute.gain.value = 0; // keep the processor running without echoing the mic
    source.connect(this.processor);
    this.processor.connect(mute);
    mute.connect(this.ctx.destination);
    await this.ctx.resume();
  }

  stopMic() {
    this.processor?.disconnect();
    this.processor = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.pending = [];
  }

  play(base64: string) {
    const bytes = fromBase64(base64);
    const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
    if (!pcm.length) return;
    const buf = this.ctx.createBuffer(1, pcm.length, SPEAKER_RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    this.playAt = Math.max(this.playAt, this.ctx.currentTime);
    src.start(this.playAt);
    this.playAt += buf.duration;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
  }

  /** The user barged in: drop everything queued. */
  stopPlayback() {
    this.sources.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    this.sources.clear();
    this.playAt = 0;
  }

  close() {
    this.stopMic();
    this.stopPlayback();
    void this.ctx.close().catch(() => undefined);
  }
}

export function InterviewPage() {
  const { eventId = "" } = useParams();
  const [mode, setMode] = useState<"voice" | "text">("voice");
  const [phase, setPhase] = useState<Phase>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [partial, setPartial] = useState<Record<Role, string>>({ interviewer: "", user: "" });
  const [text, setText] = useState("");
  const [summary, setSummary] = useState<{ text: string | null; saved: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const socket = useRef<InterviewSocket | null>(null);
  const audio = useRef<AudioIO | null>(null);
  const phaseRef = useRef<Phase>("idle");

  const go = (p: Phase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  function teardown() {
    audio.current?.close();
    audio.current = null;
    const ws = socket.current;
    socket.current = null;
    if (ws) {
      ws.onclose = null;
      ws.onmessage = null;
      ws.close();
    }
  }

  useEffect(() => teardown, []);

  function send(msg: InterviewClientMessage) {
    const ws = socket.current;
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
  }

  function onServer(msg: InterviewServerMessage, input: "voice" | "text") {
    switch (msg.type) {
      case "ready":
        go("live");
        // In voice mode the interviewer speaks the greeting and its transcript arrives as usual.
        if (input === "text") setLines([{ role: "interviewer", text: msg.greeting_text }]);
        break;
      case "transcript":
        if (msg.final) {
          setLines((prev) => [...prev, { role: msg.role, text: msg.text }]);
          setPartial((p) => ({ ...p, [msg.role]: "" }));
        } else {
          setPartial((p) => ({ ...p, [msg.role]: p[msg.role] + msg.text }));
        }
        break;
      case "audio":
        audio.current?.play(msg.data);
        break;
      case "interrupted":
        audio.current?.stopPlayback();
        break;
      case "turn_complete":
        break;
      case "interview_complete":
        setSummary({ text: msg.summary, saved: msg.summary_saved });
        audio.current?.stopMic();
        go("done");
        break;
      case "error":
        setError(msg.message || msg.code);
        teardown();
        go("error");
        break;
    }
  }

  async function start(input: "voice" | "text") {
    teardown();
    setMode(input);
    setError(null);
    setSummary(null);
    setLines([]);
    setPartial({ interviewer: "", user: "" });
    go("connecting");
    try {
      const session = await api.startInterview(eventId);
      if (input === "voice" && !api.useMocks()) {
        audio.current = new AudioIO();
        // Ask for the mic before connecting so a denial doesn't burn the token's socket.
        await audio.current.startMic((data) => send({ type: "audio", data }));
      }
      const ws = api.openInterviewSocket(session, input);
      socket.current = ws;
      ws.onopen = () => {
        if (input === "voice" && api.useMocks()) send({ type: "audio", data: "" });
      };
      ws.onmessage = (ev) => {
        try {
          onServer(JSON.parse(String(ev.data)) as InterviewServerMessage, input);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onerror = () => setError("Couldn't reach the interview service.");
      ws.onclose = () => {
        audio.current?.stopMic();
        if (phaseRef.current === "connecting" || phaseRef.current === "live") {
          setError((e) => e ?? "The interview connection closed.");
          go("error");
        } else if (phaseRef.current === "ending") {
          go("done");
        }
      };
    } catch (e) {
      teardown();
      setError(
        e instanceof DOMException
          ? "Microphone unavailable. Allow mic access (HTTPS or localhost), or type instead."
          : errorMessage(e, "Couldn't start the interview"),
      );
      go("error");
    }
  }

  function sendText(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || phase !== "live") return;
    // The server doesn't echo typed text back as a transcript.
    setLines((prev) => [...prev, { role: "user", text: t }]);
    send({ type: "text", text: t });
    setText("");
  }

  function finish() {
    if (phase !== "live") return;
    audio.current?.stopMic();
    go("ending");
    send({ type: "end" });
  }

  const live = phase === "live";
  const shown: Line[] = [
    ...lines,
    ...(["user", "interviewer"] as Role[])
      .filter((r) => partial[r].trim())
      .map((r) => ({ role: r, text: `${partial[r]}…` })),
  ];

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Optional voice intro</h1>
      <p className="su-page-sub">
        A few minutes with Gemini. Mic needs HTTPS off localhost. You can type instead anytime.
      </p>

      <div className="su-grid-2">
        <section className="su-card" style={{ padding: "1.25rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button
              type="button"
              className={`su-btn ${mode === "voice" ? "su-btn-primary" : "su-btn-secondary"}`}
              disabled={phase === "connecting" || phase === "ending" || (live && mode === "voice")}
              onClick={() => void start("voice")}
            >
              {live && mode === "voice" ? "Listening…" : phase === "connecting" && mode === "voice" ? "Connecting…" : "Start voice"}
            </button>
            <button
              type="button"
              className={`su-btn ${mode === "text" ? "su-btn-primary" : "su-btn-secondary"}`}
              disabled={phase === "connecting" || phase === "ending" || (live && mode === "text")}
              onClick={() => void start("text")}
            >
              Type instead
            </button>
          </div>

          <div
            aria-live="polite"
            style={{
              minHeight: 220,
              background: "#0d1a13",
              color: "#fff",
              borderRadius: 14,
              padding: "1rem",
              display: "grid",
              alignContent: "start",
              gap: "0.75rem",
            }}
          >
            {live && mode === "voice" ? <p className="su-pulse">● Mic live · PCM16 @ 16 kHz</p> : null}
            {phase === "idle" ? (
              <p style={{ opacity: 0.75 }}>Start a voice or text interview when you're ready.</p>
            ) : null}
            {phase === "connecting" ? <p style={{ opacity: 0.75 }}>Connecting…</p> : null}
            {shown.map((line, i) => (
              <div key={i} style={{ opacity: line.role === "interviewer" ? 0.9 : 1 }}>
                <strong style={{ color: line.role === "interviewer" ? "#5eceba" : "#ecd5a8" }}>
                  {line.role === "interviewer" ? "Interviewer" : "You"}
                </strong>
                <p style={{ margin: "0.2rem 0 0", lineHeight: 1.5 }}>{line.text}</p>
              </div>
            ))}
            {phase === "ending" ? <p style={{ opacity: 0.75 }}>Summarizing your interview…</p> : null}
          </div>

          {live ? (
            <form style={{ marginTop: "1rem", display: "flex", gap: "0.5rem" }} onSubmit={sendText}>
              <input
                className="su-input"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Type your answer…"
              />
              <button className="su-btn su-btn-primary" type="submit">
                Send
              </button>
            </form>
          ) : null}
          {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}
        </section>

        <section className="su-card" style={{ padding: "1.25rem" }}>
          <h3>When you're done</h3>
          {summary ? (
            <>
              <p style={{ lineHeight: 1.55 }}>{summary.text ?? "Nothing to summarize yet."}</p>
              <p style={{ color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                {summary.saved
                  ? "Saved to your profile. Recommendations will use it."
                  : "The summary couldn't be saved this time."}
              </p>
            </>
          ) : (
            <p style={{ color: "var(--su-text-muted)", lineHeight: 1.55 }}>
              We'll save a short summary + traits to your profile, then re-rank recommendations.
            </p>
          )}
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "1rem" }}>
            {phase === "done" ? (
              <Link className="su-btn su-btn-primary" to={`/events/${eventId}/recommendations`}>
                See recommendations
              </Link>
            ) : (
              <>
                <button
                  type="button"
                  className="su-btn su-btn-primary"
                  disabled={!live}
                  onClick={finish}
                >
                  {phase === "ending" ? "Finishing…" : "I'm done"}
                </button>
                <Link className="su-btn su-btn-secondary" to={`/events/${eventId}/recommendations`}>
                  Skip interview
                </Link>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

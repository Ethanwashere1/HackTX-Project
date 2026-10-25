import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

type Line = { role: "interviewer" | "user"; text: string };

export function InterviewPage() {
  const { eventId = "evt_hacktx" } = useParams();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"voice" | "text">("voice");
  const [listening, setListening] = useState(false);
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>([
    {
      role: "interviewer",
      text: "Hey Maya! Tell me what you want to build this weekend — and what kind of teammates help you do your best work.",
    },
  ]);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  function startMockVoice() {
    setMode("voice");
    setListening(true);
    let n = 0;
    timer.current = window.setInterval(() => {
      n += 1;
      if (n === 1) {
        setLines((prev) => [
          ...prev,
          { role: "user", text: "I'm mostly React/frontend. I want a climate or campus-tools angle." },
        ]);
      }
      if (n === 2) {
        setLines((prev) => [
          ...prev,
          {
            role: "interviewer",
            text: "Love that. Competitive or chill builder energy for HackTX?",
          },
        ]);
      }
      if (n === 3) {
        setListening(false);
        if (timer.current) window.clearInterval(timer.current);
        setLines((prev) => [
          ...prev,
          {
            role: "user",
            text: "Chill but ambitious — I want to ship something people actually use.",
          },
        ]);
      }
    }, 1600);
  }

  function sendText(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setLines((prev) => [...prev, { role: "user", text: text.trim() }]);
    setText("");
    window.setTimeout(() => {
      setLines((prev) => [
        ...prev,
        {
          role: "interviewer",
          text: "Got it — I'll summarize this onto your profile for matching.",
        },
      ]);
    }, 700);
  }

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Optional voice intro</h1>
      <p className="su-page-sub">
        About 60 seconds with Gemini. Mic needs HTTPS off localhost. You can type instead anytime.
      </p>

      <div className="su-grid-2">
        <section className="su-card" style={{ padding: "1.25rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button
              type="button"
              className={`su-btn ${mode === "voice" ? "su-btn-primary" : "su-btn-secondary"}`}
              onClick={() => startMockVoice()}
            >
              {listening ? "Listening…" : "Start voice"}
            </button>
            <button
              type="button"
              className={`su-btn ${mode === "text" ? "su-btn-primary" : "su-btn-secondary"}`}
              onClick={() => {
                setMode("text");
                setListening(false);
              }}
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
              gap: "0.75rem",
            }}
          >
            {listening ? <p className="su-pulse">● Mic live · PCM16 @ 16 kHz (mock)</p> : null}
            {lines.map((line, i) => (
              <div key={i} style={{ opacity: line.role === "interviewer" ? 0.9 : 1 }}>
                <strong style={{ color: line.role === "interviewer" ? "#5eceba" : "#ecd5a8" }}>
                  {line.role === "interviewer" ? "Interviewer" : "You"}
                </strong>
                <p style={{ margin: "0.2rem 0 0", lineHeight: 1.5 }}>{line.text}</p>
              </div>
            ))}
          </div>

          {mode === "text" ? (
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
        </section>

        <section className="su-card" style={{ padding: "1.25rem" }}>
          <h3>When you're done</h3>
          <p style={{ color: "var(--su-text-muted)", lineHeight: 1.55 }}>
            We'll save a short summary + traits to your profile, then re-rank recommendations.
          </p>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "1rem" }}>
            <button
              type="button"
              className="su-btn su-btn-primary"
              onClick={() => navigate(`/events/${eventId}/recommendations`)}
            >
              I'm done
            </button>
            <Link className="su-btn su-btn-secondary" to={`/events/${eventId}/recommendations`}>
              Skip interview
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}

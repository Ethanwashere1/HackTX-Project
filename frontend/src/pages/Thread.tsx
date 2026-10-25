import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Thread } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function ThreadPage() {
  const { threadId = "thr_1" } = useParams();
  const { me } = useAuth();
  const [thread, setThread] = useState<Thread | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setThread(await api.getThread(threadId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chat");
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(id);
  }, [threadId]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await api.sendMessage(threadId, text.trim());
    setText("");
    await load();
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!thread) return <div className="su-page">Loading chat…</div>;

  return (
    <div className="su-page su-fade-up">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h1 className="su-page-title">{thread.title}</h1>
          <p className="su-page-sub">Pre-join chat · polling every 2s</p>
        </div>
        <a className="su-btn su-btn-primary" href={thread.call_url} target="_blank" rel="noreferrer">
          Start video call
        </a>
      </div>

      <div
        className="su-card"
        style={{ padding: "1rem", minHeight: 320, display: "grid", gap: "0.75rem", marginBottom: "1rem" }}
        aria-live="polite"
      >
        {thread.messages.map((m) => {
          const mine = m.sender_id === me?.user_id;
          return (
            <div
              key={m.message_id}
              style={{
                justifySelf: mine ? "end" : "start",
                maxWidth: "70%",
                background: mine ? "var(--su-teal)" : "#fff",
                color: mine ? "#fff" : "var(--su-text)",
                border: mine ? "none" : "1px solid var(--su-border)",
                borderRadius: 14,
                padding: "0.75rem 0.9rem",
              }}
            >
              <strong style={{ fontSize: "0.75rem", opacity: 0.85 }}>{m.sender_name}</strong>
              <p style={{ margin: "0.25rem 0 0", lineHeight: 1.45 }}>{m.text}</p>
            </div>
          );
        })}
      </div>

      <form onSubmit={(e) => void send(e)} style={{ display: "flex", gap: "0.6rem" }}>
        <input
          className="su-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write a message…"
        />
        <button className="su-btn su-btn-primary" type="submit">
          Send
        </button>
      </form>
    </div>
  );
}

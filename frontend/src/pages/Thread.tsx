import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import type { Message, ThreadInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const POLL_MS = 2000;

const KIND_COPY: Record<ThreadInfo["kind"], string> = {
  request: "Pre-join chat",
  group: "Team chat",
  connection: "Connection chat",
};

/** Appends new messages, skipping ones already shown (a sent message can also arrive by poll). */
function merge(prev: Message[], incoming: Message[]): Message[] {
  if (!incoming.length) return prev;
  const seen = new Set(prev.map((m) => m.message_id));
  const fresh = incoming.filter((m) => !seen.has(m.message_id));
  return fresh.length ? [...prev, ...fresh] : prev;
}

export function ThreadPage() {
  const { threadId = "" } = useParams();
  // Keyed so switching threads starts from fresh state.
  return <ThreadView key={threadId} threadId={threadId} />;
}

function ThreadView({ threadId }: { threadId: string }) {
  const { me } = useAuth();
  const [thread, setThread] = useState<ThreadInfo | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [callUrl, setCallUrl] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const lastId = useRef<string | undefined>(undefined);

  // Thread info and the (stable) call link once; then poll only /messages?after=.
  useEffect(() => {
    let live = true;
    api
      .getThread(threadId)
      .then((t) => live && setThread(t))
      .catch((e: unknown) => live && setError(errorMessage(e, "Failed to load chat")));
    api
      .callUrl(threadId)
      .then((u) => live && setCallUrl(u))
      .catch(() => undefined);

    async function poll() {
      try {
        const batch = await api.listMessages(threadId, lastId.current);
        if (!live || !batch.length) return;
        lastId.current = batch[batch.length - 1].message_id;
        setMessages((prev) => merge(prev, batch));
      } catch (e) {
        if (live) setError(errorMessage(e, "Failed to load chat"));
      }
    }
    void poll();
    const id = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, [threadId]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setSending(true);
    setSendError(null);
    try {
      const msg = await api.sendMessage(threadId, t);
      setMessages((prev) => merge(prev, [msg]));
      setText("");
    } catch (err) {
      setSendError(errorMessage(err, "Couldn't send"));
    } finally {
      setSending(false);
    }
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!thread) return <div className="su-page">Loading chat…</div>;

  const names = new Map(thread.participants.map((p) => [p.user_id, p.name]));
  const others = thread.participants.filter((p) => p.user_id !== me?.user_id).map((p) => p.name);

  return (
    <div className="su-page su-fade-up">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h1 className="su-page-title">{thread.title ?? (others.join(", ") || "Chat")}</h1>
          <p className="su-page-sub">
            {KIND_COPY[thread.kind]}
            {others.length ? ` · with ${others.join(", ")}` : ""} ·{" "}
            {thread.group_id && thread.kind === "group" ? (
              <Link to={`/groups/${thread.group_id}`}>Team page</Link>
            ) : (
              <Link to={`/events/${thread.event_id}`}>Event</Link>
            )}
          </p>
        </div>
        {callUrl ? (
          <a className="su-btn su-btn-primary" href={callUrl} target="_blank" rel="noreferrer">
            Start video call
          </a>
        ) : null}
      </div>

      <div
        className="su-card"
        style={{ padding: "1rem", minHeight: 320, display: "grid", alignContent: "start", gap: "0.75rem", marginBottom: "1rem" }}
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p style={{ color: "var(--su-text-muted)", margin: 0 }}>No messages yet. Say hi!</p>
        ) : null}
        {messages.map((m) => {
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
              <strong style={{ fontSize: "0.75rem", opacity: 0.85 }}>
                {mine ? "You" : (m.sender_name ?? names.get(m.sender_id) ?? "Someone")}
              </strong>
              <p style={{ margin: "0.25rem 0 0", lineHeight: 1.45 }}>{m.text}</p>
            </div>
          );
        })}
      </div>

      <form
        className="su-chat-compose"
        onSubmit={(e) => void send(e)}
        style={{ display: "flex", gap: "0.6rem" }}
      >
        <input
          className="su-input"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write a message…"
        />
        <button className="su-btn su-btn-primary" type="submit" disabled={sending}>
          Send
        </button>
      </form>
      {sendError ? <p style={{ color: "var(--su-danger)" }}>{sendError}</p> : null}
    </div>
  );
}

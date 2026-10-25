import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EventDetail } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function EventDetailsPage() {
  const { eventId = "evt_hacktx" } = useParams();
  const { me } = useAuth();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .getEvent(eventId)
      .then(setEvent)
      .catch((e: Error) => setError(e.message));
  }, [eventId]);

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!event) return <div className="su-page">Loading event…</div>;

  const joined = Boolean(event.my_membership);
  const isHost = Boolean(me && event.host.user_id === me.user_id);

  return (
    <div className="su-page su-fade-up">
      <span className={`su-badge ${event.type === "structured" ? "su-badge-warm" : "su-badge-teal"}`}>
        {event.type === "structured" ? "Squad event" : "1:1 connection"}
      </span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        {event.name}
      </h1>
      <p className="su-page-sub">{event.description}</p>

      <div className="su-grid-2">
        <article className="su-card" style={{ padding: "1.2rem" }}>
          <h3>Details</h3>
          <ul style={{ color: "var(--su-text-muted)", lineHeight: 1.8 }}>
            <li>Tone: {event.tone}</li>
            <li>
              Host: {event.host.name}
              {isHost ? " (you)" : ""}
            </li>
            <li>
              Members: {event.stats.member_count}
              {event.type === "structured"
                ? ` · Squads formed: ${event.stats.groups_formed}/${event.group_count}`
                : null}
            </li>
            {event.type === "structured" ? (
              <li>
                Squad size {event.min_size}–{event.max_size}
              </li>
            ) : null}
            <li>Questions: {event.questions.length}</li>
            <li>Interview: {event.interview_enabled ? "Optional voice intro available" : "Off"}</li>
          </ul>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            {isHost ? (
              <p style={{ margin: 0, color: "var(--su-text-muted)", lineHeight: 1.5 }}>
                You’re the host — you manage this event and can’t join it as a participant.
              </p>
            ) : !joined ? (
              <Link className="su-btn su-btn-primary" to={`/events/${event.event_id}/join`}>
                Join event
              </Link>
            ) : (
              <>
                <Link
                  className="su-btn su-btn-primary"
                  to={`/events/${event.event_id}/recommendations`}
                >
                  See recommendations
                </Link>
                {event.interview_enabled ? (
                  <Link className="su-btn su-btn-secondary" to={`/events/${event.event_id}/interview`}>
                    Voice intro
                  </Link>
                ) : null}
              </>
            )}
          </div>
        </article>

        <article className="su-card" style={{ padding: "1.2rem" }}>
          <h3>Questionnaire preview ({event.questions.length})</h3>
          <ol style={{ color: "var(--su-text-muted)", lineHeight: 1.7 }}>
            {event.questions.map((q) => (
              <li key={q.question_id}>
                {q.text}
                {q.required ? " *" : ""}
                {q.options ? ` (${q.options.join(", ")})` : ""}
              </li>
            ))}
          </ol>
          <p style={{ fontSize: "0.85rem", color: "var(--su-text-muted)" }}>
            Share link: {event.share_url}
          </p>
        </article>
      </div>
    </div>
  );
}

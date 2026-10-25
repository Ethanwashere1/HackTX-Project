import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EventDetail } from "../api/types";

export function EventDetailsPage() {
  const { eventId = "evt_hacktx" } = useParams();
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

  return (
    <div className="su-page su-fade-up">
      <span className={`su-badge ${event.type === "structured" ? "su-badge-warm" : "su-badge-teal"}`}>
        {event.type === "structured" ? "Team event" : "1:1 connection"}
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
            <li>Host: {event.host.name}</li>
            <li>
              Members: {event.stats.member_count}
              {event.type === "structured"
                ? ` · Groups formed: ${event.stats.groups_formed}/${event.group_count}`
                : null}
            </li>
            {event.type === "structured" ? (
              <li>
                Group size {event.min_size}–{event.max_size}
              </li>
            ) : null}
            <li>Interview: {event.interview_enabled ? "Optional voice intro available" : "Off"}</li>
          </ul>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            {!joined ? (
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
          <h3>Questionnaire preview</h3>
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

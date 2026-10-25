import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import { formatWhen } from "../api/format";
import type { EventDetail } from "../api/types";

export function EventDetailsPage() {
  const { eventId = "" } = useParams();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [error, setError] = useState<{ code: string | null; message: string } | null>(null);

  useEffect(() => {
    api
      .getEvent(eventId)
      .then(setEvent)
      .catch((e: unknown) =>
        setError({ code: e instanceof ApiError ? e.code : null, message: errorMessage(e) }),
      );
  }, [eventId]);

  if (error?.code === "not_org_member") {
    return (
      <div className="su-page su-fade-up">
        <h1 className="su-page-title">Members only</h1>
        <article className="su-card" style={{ padding: "1.2rem", maxWidth: 720 }}>
          <p>This event belongs to an organization you haven't joined yet. Join the org to see it.</p>
          <Link className="su-btn su-btn-primary" to="/orgs">
            Find the organization
          </Link>
        </article>
      </div>
    );
  }
  if (error) return <div className="su-page">Error: {error.message}</div>;
  if (!event) return <div className="su-page">Loading event…</div>;

  const joined = Boolean(event.my_membership);
  const groupId = event.my_membership?.group_id ?? null;
  const structured = event.type === "structured";

  return (
    <div className="su-page su-fade-up">
      <span className={`su-badge ${structured ? "su-badge-warm" : "su-badge-teal"}`}>
        {structured ? "Team event" : "1:1 connection"}
      </span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        {event.name}
      </h1>
      <p className="su-page-sub">{event.description}</p>

      <div className="su-grid-2">
        <article className="su-card" style={{ padding: "1.2rem" }}>
          <h3>Details</h3>
          <ul style={{ color: "var(--su-text-muted)", lineHeight: 1.8 }}>
            <li>Starts: {formatWhen(event.starts_at)}</li>
            <li>Tone: {event.tone}</li>
            <li>Host: {event.host.name}</li>
            <li>
              Members: {event.stats.member_count}
              {structured
                ? ` · Groups formed: ${event.stats.groups_formed}/${event.group_count}`
                : null}
            </li>
            {structured ? (
              <li>
                Group size {event.min_size}–{event.max_size}
                {event.max_groups_per_user && event.max_groups_per_user > 1
                  ? ` · up to ${event.max_groups_per_user} groups each`
                  : null}
              </li>
            ) : null}
            <li>Interview: {event.interview_enabled ? "Optional voice intro available" : "Off"}</li>
            {joined ? <li>You joined {formatWhen(event.my_membership?.joined_at)}</li> : null}
          </ul>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            {!joined ? (
              <Link className="su-btn su-btn-primary" to={`/events/${event.event_id}/join`}>
                Join event
              </Link>
            ) : (
              <>
                {groupId ? (
                  <Link className="su-btn su-btn-primary" to={`/groups/${groupId}`}>
                    Open your team
                  </Link>
                ) : null}
                <Link
                  className={`su-btn ${groupId ? "su-btn-secondary" : "su-btn-primary"}`}
                  to={`/events/${event.event_id}/recommendations`}
                >
                  {structured ? "See recommendations" : "Recommendations & connections"}
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

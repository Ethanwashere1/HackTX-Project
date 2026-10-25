import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import type { GroupPage } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "../components/Avatar";

export function GroupPageView() {
  const { groupId = "" } = useParams();
  const { me } = useAuth();
  const [group, setGroup] = useState<GroupPage | null>(null);
  const [eventName, setEventName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getGroup(groupId)
      .then((g) => {
        setGroup(g);
        // The squad page body has only event_id; the name is a nicety.
        return api.getEvent(g.event_id).then((e) => setEventName(e.name)).catch(() => undefined);
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [groupId]);

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!group) return <div className="su-page">Loading squad…</div>;

  const isOwner = Boolean(me && group.owner_user_id === me.user_id);
  const owner = group.members.find((m) => m.user_id === group.owner_user_id);

  return (
    <div className="su-page su-fade-up">
      <span className="su-badge su-badge-warm">Formed squad</span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        {group.name}
      </h1>
      <p className="su-page-sub">
        {eventName ?? "Event"} · {group.members.length} members · contacts visible to members only
        {owner ? ` · Owner: ${owner.name ?? "Member"}${isOwner ? " (you)" : ""}` : ""}
      </p>
      {isOwner ? (
        <p style={{ color: "var(--su-text-muted)", marginTop: "-0.5rem" }}>
          You’re the squad owner — you can’t send a join request to your own squad.
        </p>
      ) : null}

      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
        {group.thread_id ? (
          <Link className="su-btn su-btn-primary" to={`/threads/${group.thread_id}`}>
            Open squad chat
          </Link>
        ) : null}
        <Link className="su-btn su-btn-secondary" to={`/events/${group.event_id}`}>
          Back to event
        </Link>
      </div>

      <div className="su-grid-2">
        {group.members.map((m) => (
          <article key={m.user_id} className="su-card" style={{ padding: "1.15rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <Avatar name={m.name ?? "?"} size={44} />
              <div>
                <h3 style={{ margin: 0 }}>
                  {m.name ?? "Member"}
                  {m.user_id === group.owner_user_id ? (
                    <span className="su-badge su-badge-warm" style={{ marginLeft: "0.5rem" }}>
                      Owner
                    </span>
                  ) : null}
                </h3>
                {m.user_id === me?.user_id ? (
                  <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>You</p>
                ) : null}
              </div>
            </div>
            {m.summary ? (
              <p style={{ color: "var(--su-text-muted)", lineHeight: 1.5 }}>{m.summary}</p>
            ) : null}
            {m.contacts.length ? (
              <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.7 }}>
                {m.contacts.map((c) => (
                  <li key={`${c.kind}-${c.value}`}>
                    <strong>{c.kind}</strong>: {c.value}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                No contact methods shared yet.
              </p>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

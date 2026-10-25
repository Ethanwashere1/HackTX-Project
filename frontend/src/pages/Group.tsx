import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { GroupPage } from "../api/types";
import { Avatar } from "../components/Avatar";

export function GroupPageView() {
  const { groupId = "grp_pixel" } = useParams();
  const [group, setGroup] = useState<GroupPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .getGroup(groupId)
      .then(setGroup)
      .catch((e: Error) => setError(e.message));
  }, [groupId]);

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!group) return <div className="su-page">Loading team…</div>;

  return (
    <div className="su-page su-fade-up">
      <span className="su-badge su-badge-warm">Formed team</span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        {group.name}
      </h1>
      <p className="su-page-sub">
        {group.event_name} · contacts visible to members only
      </p>

      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
        <Link className="su-btn su-btn-primary" to={`/threads/${group.thread_id}`}>
          Open team chat
        </Link>
        <Link className="su-btn su-btn-secondary" to={`/events/${group.event_id}`}>
          Back to event
        </Link>
      </div>

      <div className="su-grid-2">
        {group.members.map((m) => (
          <article key={m.user_id} className="su-card" style={{ padding: "1.15rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <Avatar name={m.name} size={44} />
              <div>
                <h3 style={{ margin: 0 }}>{m.name}</h3>
                <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                  {m.role}
                </p>
              </div>
            </div>
            {m.summary ? (
              <p style={{ color: "var(--su-text-muted)", lineHeight: 1.5 }}>{m.summary}</p>
            ) : null}
            <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.7 }}>
              {(m.contacts ?? []).map((c) => (
                <li key={`${c.kind}-${c.value}`}>
                  <strong>{c.kind}</strong>: {c.value}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

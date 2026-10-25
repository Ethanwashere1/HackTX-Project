import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import type {
  Connection,
  EventDetail,
  GroupRecommendation,
  PersonRecommendation,
  RecommendationsResponse,
} from "../api/types";

type Target = { type: "user" | "group"; id: string };

function MatchScore({ score }: { score: number }) {
  return (
    <span style={{ color: "var(--su-text-muted)", fontSize: "0.8rem" }}>
      {(Math.max(0, score) * 100).toFixed(0)}% match
    </span>
  );
}

type Loaded = {
  event: EventDetail;
  data: RecommendationsResponse | null; // null until joined
  connections: Connection[];
};

async function fetchAll(eventId: string): Promise<Loaded> {
  const event = await api.getEvent(eventId);
  if (!event.my_membership) return { event, data: null, connections: [] };
  const [data, connections] = await Promise.all([
    api.recommendations(eventId),
    // Informal events have no groups: accepted requests become connections, listed separately.
    event.type === "informal" ? api.connections(eventId) : Promise.resolve([]),
  ]);
  return { event, data, connections };
}

export function RecommendationsPage() {
  const { eventId = "" } = useParams();
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<{ code: string | null; message: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const load = () => setVersion((v) => v + 1);

  useEffect(() => {
    let live = true;
    fetchAll(eventId)
      .then((l) => {
        if (live) setLoaded(l);
      })
      .catch((e: unknown) => {
        if (live) setError({ code: e instanceof ApiError ? e.code : null, message: errorMessage(e) });
      });
    return () => {
      live = false;
    };
  }, [eventId, version]);

  const event = loaded?.event ?? null;
  const data = loaded?.data ?? null;
  const connections = loaded?.connections ?? [];

  async function request(target: Target) {
    setBusyId(target.id);
    setActionError(null);
    try {
      const res = await api.createRequest({
        event_id: eventId,
        target_type: target.type,
        target_id: target.id,
      });
      navigate(`/threads/${res.thread_id}`);
    } catch (e) {
      setActionError(errorMessage(e, "Request failed"));
      // A 409 means the candidate is no longer valid (full group, already connected...): refresh.
      if (e instanceof ApiError && e.status === 409) load();
    } finally {
      setBusyId(null);
    }
  }

  if (error?.code === "not_org_member") {
    return (
      <div className="su-page">
        This event belongs to an organization you haven't joined. <Link to="/orgs">Join the org →</Link>
      </div>
    );
  }
  if (error) return <div className="su-page">Error: {error.message}</div>;
  if (!event) return <div className="su-page">Loading recommendations…</div>;

  if (!event.my_membership) {
    return (
      <div className="su-page su-fade-up">
        <h1 className="su-page-title">{event.name}</h1>
        <p className="su-page-sub">Join the event to get recommendations.</p>
        <Link className="su-btn su-btn-primary" to={`/events/${eventId}/join`}>
          Join event
        </Link>
      </div>
    );
  }
  if (!data) return <div className="su-page">Loading recommendations…</div>;

  const structured = event.type === "structured";
  const groupId = event.my_membership.group_id;
  const allGroupsFormed =
    structured && event.group_count !== null && event.stats.groups_formed >= event.group_count;
  const empty = data.people.length === 0 && data.groups.length === 0;
  // At max_groups_per_user, both lists are empty because any accept would fail.
  const atGroupLimit = structured && empty && Boolean(groupId);

  const rankedCopy =
    data.ranked_by === "gemini" ? "Ranked by Gemini, with reasons" : "Ranked by profile similarity";

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">
        {structured ? "People and squad recommendations" : "People to connect with"}
      </h1>
      <p className="su-page-sub">
        {event.name} · {rankedCopy}. Send a request — both sides must accept.
      </p>

      {actionError ? <p style={{ color: "var(--su-danger)" }}>{actionError}</p> : null}

      {atGroupLimit ? (
        <article className="su-card" style={{ padding: "1.2rem", maxWidth: 720 }}>
          <span className="su-badge su-badge-warm">You're in a squad</span>
          <h3 style={{ margin: "0.75rem 0 0.25rem" }}>You've already got your squad</h3>
          <p style={{ color: "var(--su-text-muted)" }}>
            This event allows {event.max_groups_per_user ?? 1} squad
            {(event.max_groups_per_user ?? 1) > 1 ? "s" : ""} per person, so there's nothing more to
            request here.
          </p>
          <Link className="su-btn su-btn-primary" to={`/groups/${groupId}`}>
            Open your squad →
          </Link>
        </article>
      ) : (
        <>
          {allGroupsFormed ? (
            <p className="su-badge su-badge-soft" style={{ marginBottom: "1rem" }}>
              All {event.group_count} squads have formed, so only open squads are listed.
            </p>
          ) : null}
          {empty ? (
            <article className="su-card" style={{ padding: "1.2rem", maxWidth: 720 }}>
              <h3 style={{ marginTop: 0 }}>No recommendations right now</h3>
              <p style={{ color: "var(--su-text-muted)" }}>
                People with a pending request are in your{" "}
                <Link to="/requests">requests inbox</Link>. Check back as more people join.
              </p>
            </article>
          ) : null}

          {data.groups.length ? (
            <>
              <h3>Open squads</h3>
              <div className="su-grid-2" style={{ marginBottom: "1.5rem" }}>
                {data.groups.map((g) => (
                  <GroupCard
                    key={g.group_id}
                    group={g}
                    busy={busyId === g.group_id}
                    onRequest={() => void request({ type: "group", id: g.group_id })}
                  />
                ))}
              </div>
            </>
          ) : null}

          {data.people.length ? (
            <>
              <h3>People</h3>
              <div className="su-grid-2">
                {data.people.map((p) => (
                  <PersonCard
                    key={p.user_id}
                    person={p}
                    busy={busyId === p.user_id}
                    label={structured ? "Request to squad up" : "Request to connect"}
                    onRequest={() => void request({ type: "user", id: p.user_id })}
                  />
                ))}
              </div>
            </>
          ) : null}
        </>
      )}

      {!structured ? (
        <section style={{ marginTop: "1.5rem" }}>
          <h3>Your connections</h3>
          {connections.length === 0 ? (
            <p style={{ color: "var(--su-text-muted)" }}>No connections yet. Accepted requests show up here.</p>
          ) : (
            <div className="su-grid-2">
              {connections.map((c) => (
                <article key={c.connection_id} className="su-card" style={{ padding: "1.2rem" }}>
                  <span className="su-badge su-badge-teal">Connected</span>
                  <h3 style={{ margin: "0.75rem 0 0.25rem" }}>{c.name ?? "Someone"}</h3>
                  {c.summary ? <p style={{ color: "var(--su-text-muted)" }}>{c.summary}</p> : null}
                  <ul style={{ margin: "0 0 0.85rem", paddingLeft: "1.1rem", lineHeight: 1.7 }}>
                    {c.contacts.map((ct) => (
                      <li key={`${ct.kind}-${ct.value}`}>
                        <strong>{ct.kind}</strong>: {ct.value}
                      </li>
                    ))}
                  </ul>
                  {c.thread_id ? (
                    <Link className="su-btn su-btn-secondary" to={`/threads/${c.thread_id}`}>
                      Open chat
                    </Link>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      <p style={{ marginTop: "1.5rem" }}>
        <Link to="/requests">Open requests inbox →</Link>
      </p>
    </div>
  );
}

function PersonCard({
  person,
  busy,
  label,
  onRequest,
}: {
  person: PersonRecommendation;
  busy: boolean;
  label: string;
  onRequest: () => void;
}) {
  return (
    <article className="su-card" style={{ padding: "1.2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
        <span className="su-badge su-badge-teal">person</span>
        <MatchScore score={person.score} />
      </div>
      <h3 style={{ margin: "0.75rem 0 0.25rem" }}>{person.name}</h3>
      {person.summary ? (
        <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>{person.summary}</p>
      ) : null}
      {person.reason ? <p style={{ lineHeight: 1.55, color: "var(--su-text)" }}>{person.reason}</p> : null}
      <button
        type="button"
        className="su-btn su-btn-primary"
        style={{ marginTop: "0.85rem" }}
        disabled={busy}
        onClick={onRequest}
      >
        {busy ? "Sending…" : label}
      </button>
    </article>
  );
}

function GroupCard({
  group,
  busy,
  onRequest,
}: {
  group: GroupRecommendation;
  busy: boolean;
  onRequest: () => void;
}) {
  return (
    <article className="su-card" style={{ padding: "1.2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
        <span className="su-badge su-badge-warm">squad</span>
        <MatchScore score={group.score} />
      </div>
      <h3 style={{ margin: "0.75rem 0 0.25rem" }}>{group.name}</h3>
      <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
        {group.size} of {group.max_size} members · {group.members.map((m) => m.name).join(", ")}
      </p>
      {group.reason ? <p style={{ lineHeight: 1.55, color: "var(--su-text)" }}>{group.reason}</p> : null}
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", margin: "0.85rem 0" }}>
        <span className="su-badge su-badge-soft">
          {group.max_size - group.size} spot{group.max_size - group.size === 1 ? "" : "s"} left
        </span>
      </div>
      <button type="button" className="su-btn su-btn-primary" disabled={busy} onClick={onRequest}>
        {busy ? "Sending…" : "Request to join"}
      </button>
    </article>
  );
}

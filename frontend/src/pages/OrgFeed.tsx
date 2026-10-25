import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import utCampus from "../assets/ut-campus.png";
import { api } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import { formatWhen, verificationCopy } from "../api/format";
import type { Org, OrgFeed, OrgFeedEvent } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { JoinOrgButton } from "../components/JoinOrg";
import { JoinRequestsPanel } from "../components/JoinRequests";
import "./OrgFeed.css";

function eventTag(evt: OrgFeedEvent) {
  return evt.type === "structured"
    ? { label: "TEAM EVENT", cls: "su-badge-warm" }
    : { label: "1:1 CONNECTION", cls: "su-badge-teal" };
}

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "not_member"; org: Org | null }
  | { kind: "ready"; feed: OrgFeed; org: Org | null };

async function fetchFeed(orgId: string): Promise<State> {
  // The org itself (name, my_role) is best-effort; the feed decides access.
  const org = await api.getOrg(orgId).catch(() => null);
  try {
    return { kind: "ready", feed: await api.orgFeed(orgId), org };
  } catch (e) {
    if (e instanceof ApiError && e.code === "not_org_member") return { kind: "not_member", org };
    return { kind: "error", message: errorMessage(e) };
  }
}

export function OrgFeedPage() {
  const { id: orgId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const joinedOnly = params.get("joined") === "1";
  const { me } = useAuth();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState(0);
  const load = () => setVersion((v) => v + 1);

  useEffect(() => {
    let live = true;
    void fetchFeed(orgId).then((s) => {
      if (live) setState(s);
    });
    return () => {
      live = false;
    };
  }, [orgId, version]);

  if (state.kind === "error") return <div className="su-page">Error: {state.message}</div>;
  if (state.kind === "loading") return <div className="su-page">Loading feed…</div>;

  if (state.kind === "not_member") {
    const org = state.org;
    return (
      <div className="su-page su-fade-up">
        <h1 className="su-page-title">{org?.name ?? "Organization"}</h1>
        <article className="su-card" style={{ padding: "1.2rem", maxWidth: 720 }}>
          {org ? (
            <>
              <h3 style={{ marginTop: 0 }}>Join to see this organization's events</h3>
              <p style={{ color: "var(--su-text-muted)" }}>
                {org.member_count} members · {verificationCopy(org)}
              </p>
              <JoinOrgButton org={org} onJoined={load} />
            </>
          ) : (
            <>
              <h3 style={{ marginTop: 0 }}>You're not a member of this organization</h3>
              <p style={{ color: "var(--su-text-muted)" }}>
                It may not exist, or it isn't listed publicly. Ask an organizer for an invite link.
              </p>
              <Link className="su-btn su-btn-secondary" to="/orgs">
                Browse organizations
              </Link>
            </>
          )}
        </article>
      </div>
    );
  }

  const { feed, org } = state;
  const orgName = feed.name ?? org?.name ?? me?.orgs.find((o) => o.org_id === orgId)?.name ?? "";
  const term = search.trim().toLowerCase();
  const events = feed.events.filter(
    (e) => (!joinedOnly || e.joined) && (!term || e.name.toLowerCase().includes(term)),
  );

  function setJoinedOnly(on: boolean) {
    const next = new URLSearchParams(params);
    if (on) next.set("joined", "1");
    else next.delete("joined");
    setParams(next, { replace: true });
  }

  return (
    <div className="feed su-page su-fade-up">
      <div className="feed-hero">
        <div>
          <h1 className="su-page-title">Hey {me?.name.split(" ")[0] ?? "there"}, find your squad.</h1>
          <p className="su-page-sub">
            Good friendships start with shared moments. What will you get into?
          </p>
        </div>
        <Link className="su-btn su-btn-primary" to={`/events/new?org=${encodeURIComponent(orgId)}`}>
          + Create event
        </Link>
      </div>

      <section
        className="feed-banner"
        style={{ backgroundImage: `linear-gradient(90deg, #17394b 0%, #17394b 46%, transparent 78%), url(${utCampus})` }}
      >
        <p className="eyebrow">{orgName || "Campus life"} · Casual connections</p>
        <h2>Small moments. Shared interests.</h2>
        <p>Grab coffee, shoot photos, or form a HackTX squad — your campus, your pace.</p>
      </section>

      <div className="feed-toolbar">
        <input
          className="su-input"
          placeholder="Search events"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button
          type="button"
          className={`su-btn ${joinedOnly ? "su-btn-secondary" : "su-btn-primary"}`}
          onClick={() => setJoinedOnly(false)}
        >
          All events
        </button>
        <button
          type="button"
          className={`su-btn ${joinedOnly ? "su-btn-primary" : "su-btn-secondary"}`}
          onClick={() => setJoinedOnly(true)}
        >
          Joined
        </button>
      </div>

      <section>
        <div className="feed-section-head">
          <h3>
            {joinedOnly ? "Your events" : "Events for any vibe"}{" "}
            <span className="su-badge su-badge-soft">{events.length} upcoming</span>
          </h3>
        </div>
        {events.length === 0 ? (
          <p style={{ color: "var(--su-text-muted)" }}>
            {joinedOnly ? "You haven't joined any upcoming events here yet." : "No upcoming events yet. Create one!"}
          </p>
        ) : null}
        <div className="su-grid-2 su-grid-wide">
          {events.map((evt) => {
            const tag = eventTag(evt);
            return (
              <article key={evt.event_id} className="su-card feed-card">
                <div className="feed-card-top">
                  <span className={`su-badge ${tag.cls}`}>{tag.label}</span>
                  <span>{formatWhen(evt.starts_at)}</span>
                </div>
                <h4>{evt.name}</h4>
                <p className="feed-meta">
                  {evt.tone === "professional" ? "Professional" : "Casual"} · {evt.member_count} joined
                  {evt.joined ? " · You're in" : ""}
                </p>
                <Link
                  className={`su-btn ${evt.type === "structured" ? "su-btn-primary" : "su-btn-secondary"}`}
                  to={`/events/${evt.event_id}`}
                >
                  {evt.joined
                    ? "Open event →"
                    : evt.type === "structured"
                      ? "Explore & find teammates →"
                      : "Open event →"}
                </Link>
              </article>
            );
          })}
        </div>
      </section>

      <LocalSignals />

      <aside className="feed-aside su-card">
        <h3>How matching works</h3>
        <ol>
          <li>Browse an event and share your interests</li>
          <li>Get recommendations with reasons</li>
          <li>Chat / meet — both sides accept</li>
        </ol>
        <Link className="su-btn su-btn-secondary" to="/profile">
          Finish your profile
        </Link>
      </aside>

      {org?.my_role === "admin" ? <JoinRequestsPanel orgId={orgId} /> : null}
    </div>
  );
}

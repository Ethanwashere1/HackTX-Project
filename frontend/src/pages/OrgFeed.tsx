import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import utCampus from "../assets/ut-campus.png";
import { api } from "../api/client";
import type { OrgFeed } from "../api/types";
import { LocalSignals } from "../components/LocalSignals";
import { useAuth } from "../auth/AuthContext";
import "./OrgFeed.css";

function tagClass(tag?: string) {
  if (!tag) return "su-badge-soft";
  if (tag.includes("SQUAD") || tag.includes("TEAM")) return "su-badge-warm";
  if (tag.includes("1:1")) return "su-badge-teal";
  if (tag.includes("SOCIAL")) return "su-badge-coral";
  return "su-badge-soft";
}

export function OrgFeedPage() {
  const { me } = useAuth();
  const [feed, setFeed] = useState<OrgFeed | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .orgFeed("org_ut")
      .then(setFeed)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!feed) return <div className="su-page">Loading feed…</div>;

  return (
    <div className="feed su-page su-fade-up">
      <div className="feed-hero">
        <div>
          <h1 className="su-page-title">Hey {me?.name.split(" ")[0] ?? "there"}, find your squad.</h1>
          <p className="su-page-sub">
            Good friendships start with shared moments. What will you get into?
          </p>
        </div>
        <Link className="su-btn su-btn-primary" to="/events/new">
          + Create event
        </Link>
      </div>

      <section
        className="feed-banner"
        style={{ backgroundImage: `linear-gradient(90deg, #17394b 0%, #17394b 46%, transparent 78%), url(${utCampus})` }}
      >
        <p className="eyebrow">Campus life · Casual connections</p>
        <h2>Small moments. Shared interests.</h2>
        <p>Grab coffee, shoot photos, or form a HackTX squad — your campus, your pace.</p>
      </section>

      <div className="feed-toolbar">
        <input className="su-input" placeholder="Search events, interests, or people" />
        <button type="button" className="su-btn su-btn-secondary">
          All events
        </button>
        <button type="button" className="su-btn su-btn-secondary">
          This month
        </button>
      </div>

      <section>
        <div className="feed-section-head">
          <h3>
            Events for any vibe <span className="su-badge su-badge-soft">{feed.events.length} upcoming</span>
          </h3>
          <Link to="/events/new">All events →</Link>
        </div>
        <div className="su-grid-2 su-grid-wide">
          {feed.events.map((evt) => (
            <article key={evt.event_id} className="su-card feed-card">
              <div className="feed-card-top">
                <span className={`su-badge ${tagClass(evt.tag)}`}>{evt.tag}</span>
                <span>
                  {evt.starts_at
                    ? new Date(evt.starts_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })
                    : "TBD"}
                </span>
              </div>
              <h4>{evt.name}</h4>
              <p>{evt.description}</p>
              <p className="feed-meta">
                {evt.location} · {evt.member_count} joined
              </p>
              <Link
                className={`su-btn ${evt.type === "structured" ? "su-btn-primary" : "su-btn-secondary"}`}
                to={`/events/${evt.event_id}`}
              >
                {evt.type === "structured" ? "Explore & find your squad →" : "Open event →"}
              </Link>
            </article>
          ))}
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
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { verificationCopy } from "../api/format";
import type { Org } from "../api/types";
import { JoinOrgButton } from "../components/JoinOrg";

/** GET /api/orgs: the user's orgs plus discoverable ones, with join actions. */
export function OrgsPage() {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState<Org[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listOrgs()
      .then(setOrgs)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!orgs) return <div className="su-page">Loading organizations…</div>;

  return (
    <div className="su-page su-fade-up">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div>
          <h1 className="su-page-title">Organizations</h1>
          <p className="su-page-sub">Your spaces, and communities you can ask to join.</p>
        </div>
        <Link className="su-btn su-btn-primary" to="/orgs/new">
          + Create organization
        </Link>
      </div>

      {orgs.length === 0 ? (
        <article className="su-card" style={{ padding: "1.2rem", maxWidth: 720 }}>
          <h3>No organizations yet</h3>
          <p style={{ color: "var(--su-text-muted)" }}>
            Create one, or open an invite link from an organizer.
          </p>
        </article>
      ) : (
        <div className="su-grid-2">
          {orgs.map((org) => (
            <article key={org.org_id} className="su-card" style={{ padding: "1.2rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                <h3 style={{ margin: 0 }}>{org.name}</h3>
                {org.my_role === "admin" ? <span className="su-badge su-badge-warm">Admin</span> : null}
              </div>
              <p style={{ color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                {org.member_count} members · {verificationCopy(org)}
              </p>
              {org.my_status === "approved" ? (
                <Link className="su-btn su-btn-secondary" to={`/orgs/${org.org_id}`}>
                  Open →
                </Link>
              ) : (
                <JoinOrgButton org={org} onJoined={() => navigate(`/orgs/${org.org_id}`)} />
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import type { Verification } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function CreateOrgPage() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [name, setName] = useState("");
  const [verification, setVerification] = useState<Verification>("email_domain");
  const [domains, setDomains] = useState("utexas.edu");
  const [discoverable, setDiscoverable] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.createOrg({
        name: name.trim(),
        verification,
        email_domains:
          verification === "email_domain"
            ? domains.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean)
            : [],
        discoverable,
      });
      await refresh(); // the creator is the first admin, so GET /api/me now lists the org
      navigate(`/orgs/${res.org_id}`);
    } catch (err) {
      setError(errorMessage(err, "Could not create the organization"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="su-page su-fade-up">
      <span className="su-badge su-badge-teal">New organization</span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        Create an organization
      </h1>
      <p className="su-page-sub">
        Bring people, groups, and events together under one shared purpose.
      </p>

      <form className="su-card" style={{ padding: "1.25rem", maxWidth: 720 }} onSubmit={(e) => void onSubmit(e)}>
        <div className="su-field">
          <label className="su-label" htmlFor="org-name">
            Organization name
          </label>
          <input
            id="org-name"
            className="su-input"
            value={name}
            placeholder="Austin Creative Collective"
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="su-field">
          <label className="su-label" htmlFor="org-verification">
            Verification
          </label>
          <select
            id="org-verification"
            className="su-select"
            value={verification}
            onChange={(e) => setVerification(e.target.value as Verification)}
          >
            <option value="manual">Manual approval</option>
            <option value="email_domain">Email domain</option>
            <option value="roster">Roster (upload a member list later)</option>
          </select>
        </div>
        {verification === "email_domain" ? (
          <div className="su-field">
            <label className="su-label" htmlFor="org-domains">
              Email domains (comma-separated)
            </label>
            <input
              id="org-domains"
              className="su-input"
              value={domains}
              required
              onChange={(e) => setDomains(e.target.value)}
            />
          </div>
        ) : null}
        <label className="su-label" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input type="checkbox" checked={discoverable} onChange={(e) => setDiscoverable(e.target.checked)} />
          Listed publicly (otherwise people join by link)
        </label>
        {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}
        <button className="su-btn su-btn-primary" type="submit" disabled={busy} style={{ marginTop: "1rem" }}>
          {busy ? "Creating…" : "Create organization"}
        </button>
      </form>
    </div>
  );
}

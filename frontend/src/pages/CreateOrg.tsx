import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

export function CreateOrgPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("Austin Creative Collective");
  const [verification, setVerification] = useState("email_domain");
  const [domains, setDomains] = useState("utexas.edu");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    // Mock create → return to UT feed for demo continuity
    navigate("/orgs/org_ut");
  }

  return (
    <div className="su-page su-fade-up">
      <span className="su-badge su-badge-teal">New organization</span>
      <h1 className="su-page-title" style={{ marginTop: "0.75rem" }}>
        Create an organization
      </h1>
      <p className="su-page-sub">
        Bring people, squads, and events together under one shared purpose.
      </p>

      <form className="su-card" style={{ padding: "1.25rem", maxWidth: 720 }} onSubmit={onSubmit}>
        <div className="su-field">
          <label className="su-label">Organization name</label>
          <input className="su-input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="su-field">
          <label className="su-label">Verification</label>
          <select
            className="su-select"
            value={verification}
            onChange={(e) => setVerification(e.target.value)}
          >
            <option value="manual">Manual approval</option>
            <option value="email_domain">Email domain</option>
            <option value="roster">Roster upload</option>
          </select>
        </div>
        {verification === "email_domain" ? (
          <div className="su-field">
            <label className="su-label">Email domains</label>
            <input className="su-input" value={domains} onChange={(e) => setDomains(e.target.value)} />
          </div>
        ) : null}
        <button className="su-btn su-btn-primary" type="submit">
          Create organization
        </button>
      </form>
    </div>
  );
}

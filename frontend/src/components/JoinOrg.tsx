import { useState } from "react";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import type { Org, OrgStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";

/** POST /api/orgs/{id}/join. Calls `onJoined` when the request is approved right away. */
export function JoinOrgButton({
  org,
  onJoined,
}: {
  org: Org;
  onJoined?: () => void;
}) {
  const { refresh } = useAuth();
  const [status, setStatus] = useState<OrgStatus | null>(org.my_status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function join() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.joinOrg(org.org_id);
      setStatus(res.status);
      if (res.status === "approved") {
        await refresh(); // GET /api/me now lists the org
        onJoined?.();
      }
    } catch (e) {
      setError(errorMessage(e, "Could not send the request"));
    } finally {
      setBusy(false);
    }
  }

  if (status === "approved") return <span className="su-badge su-badge-teal">Member</span>;

  return (
    <div style={{ display: "grid", gap: "0.4rem", justifyItems: "start" }}>
      {status === "pending" ? (
        <span className="su-badge su-badge-warm">Request pending · waiting for an admin</span>
      ) : (
        <button type="button" className="su-btn su-btn-primary" disabled={busy} onClick={() => void join()}>
          {busy ? "Sending…" : status === "declined" ? "Ask again" : "Request to join"}
        </button>
      )}
      {status === "declined" ? (
        <small style={{ color: "var(--su-text-muted)" }}>
          Your last request was declined; a new one waits for an admin.
        </small>
      ) : null}
      {error ? <small style={{ color: "var(--su-danger)" }}>{error}</small> : null}
    </div>
  );
}

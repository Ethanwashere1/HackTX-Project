import { useEffect, useState } from "react";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { formatWhen } from "../api/format";
import type { JoinRequest } from "../api/types";

/** Admin-only: pending org join requests with approve / decline. */
export function JoinRequestsPanel({ orgId }: { orgId: string }) {
  const [items, setItems] = useState<JoinRequest[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .joinRequests(orgId)
      .then(setItems)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [orgId]);

  async function decide(userId: string, action: "approve" | "decline") {
    setBusy(userId);
    setError(null);
    try {
      await api.decideJoinRequest(orgId, userId, action);
      setItems(await api.joinRequests(orgId));
    } catch (e) {
      setError(errorMessage(e));
      // request_not_pending: another admin got there first; show the current list.
      setItems(await api.joinRequests(orgId).catch(() => items));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="su-card" style={{ padding: "1.15rem", marginTop: "1.25rem" }}>
      <h3 style={{ marginTop: 0 }}>
        Join requests{" "}
        {items?.length ? <span className="su-badge su-badge-warm">{items.length} pending</span> : null}
      </h3>
      {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}
      {!items ? (
        <p style={{ color: "var(--su-text-muted)" }}>Loading…</p>
      ) : items.length === 0 ? (
        <p style={{ color: "var(--su-text-muted)" }}>No pending requests.</p>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {items.map((r) => (
            <div
              key={r.user_id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: "1rem",
                flexWrap: "wrap",
                borderTop: "1px solid var(--su-border)",
                paddingTop: "0.75rem",
              }}
            >
              <div>
                <strong>{r.name}</strong>{" "}
                <span style={{ color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                  {r.email} · {formatWhen(r.requested_at, "")}
                </span>
                {r.roster_match === "name" ? (
                  <div>
                    <span className="su-badge su-badge-soft" title="Names are self-chosen, so this is only a hint">
                      Matches a roster name, not verified
                    </span>
                  </div>
                ) : r.roster_match === "email" ? (
                  <div>
                    <span className="su-badge su-badge-teal">Email is on the roster</span>
                  </div>
                ) : null}
                {r.message ? (
                  <p style={{ margin: "0.35rem 0 0", color: "var(--su-text-muted)" }}>“{r.message}”</p>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "start" }}>
                <button
                  type="button"
                  className="su-btn su-btn-primary"
                  disabled={busy !== null}
                  onClick={() => void decide(r.user_id, "approve")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="su-btn su-btn-secondary"
                  disabled={busy !== null}
                  onClick={() => void decide(r.user_id, "decline")}
                >
                  Decline
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

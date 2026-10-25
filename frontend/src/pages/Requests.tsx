import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { formatWhen } from "../api/format";
import type { RequestDecision, RequestItem } from "../api/types";

type Action = "accept" | "decline" | "cancel";

const STATUS_BADGE: Record<RequestItem["status"], string> = {
  pending: "su-badge-warm",
  accepted: "su-badge-teal",
  declined: "su-badge-soft",
  cancelled: "su-badge-soft",
  expired: "su-badge-soft",
};

function outcomeLink(item: { event_id: string; group_id: string | null; connection_id: string | null }) {
  if (item.group_id) return { to: `/groups/${item.group_id}`, label: "Open team" };
  if (item.connection_id) return { to: `/events/${item.event_id}/recommendations`, label: "See connection" };
  return null;
}

/** Both boxes, newest first. `direction` echoes the box, so each needs its own call. */
async function fetchRequests(): Promise<RequestItem[]> {
  const [incoming, outgoing] = await Promise.all([
    api.listRequests("incoming"),
    api.listRequests("outgoing"),
  ]);
  return [...incoming, ...outgoing].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** Requests carry only event_id; look up the names (best-effort). */
async function fetchEventNames(items: RequestItem[]): Promise<Record<string, string>> {
  const ids = [...new Set(items.map((r) => r.event_id))];
  const named = await Promise.all(
    ids.map((id) =>
      api
        .getEvent(id)
        .then((e) => [id, e.name] as const)
        .catch(() => null),
    ),
  );
  return Object.fromEntries(named.filter((x) => x !== null));
}

export function RequestsPage() {
  const [items, setItems] = useState<RequestItem[] | null>(null);
  const [eventNames, setEventNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; link: { to: string; label: string } | null } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    fetchRequests()
      .then(async (all) => {
        if (!live) return;
        setItems(all);
        const names = await fetchEventNames(all);
        if (live) setEventNames(names);
      })
      .catch((e: unknown) => {
        if (live) setError(errorMessage(e, "Failed to load"));
      });
    return () => {
      live = false;
    };
  }, [version]);

  async function respond(item: RequestItem, action: Action) {
    setBusy(item.request_id);
    setNotice(null);
    try {
      const res: RequestDecision = await api.respondRequest(item.request_id, action);
      if (action === "accept") {
        setNotice({
          text: res.group_id
            ? `You're now in a group with ${item.other_party.name ?? "them"}.`
            : `You're connected with ${item.other_party.name ?? "them"}.`,
          link: outcomeLink({ event_id: item.event_id, ...res }),
        });
      }
    } catch (e) {
      setNotice({ text: errorMessage(e), link: null });
    } finally {
      setBusy(null);
      // Accepting can settle other pending requests too (crossing or now-redundant ones): reload.
      setVersion((v) => v + 1);
    }
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!items) return <div className="su-page">Loading requests…</div>;

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Requests</h1>
      <p className="su-page-sub">Mutual consent inbox — nothing forms until both sides say yes.</p>

      {notice ? (
        <article className="su-card" style={{ padding: "0.9rem 1.1rem", maxWidth: 820, marginBottom: "1rem" }}>
          {notice.text}{" "}
          {notice.link ? <Link to={notice.link.to}>{notice.link.label} →</Link> : null}
        </article>
      ) : null}

      {items.length === 0 ? (
        <p style={{ color: "var(--su-text-muted)" }}>
          No requests yet. Send one from an event's recommendations.
        </p>
      ) : null}

      <div style={{ display: "grid", gap: "0.85rem", maxWidth: 820 }}>
        {items.map((item) => {
          const pending = item.status === "pending";
          const outcome = outcomeLink(item);
          const incoming = item.direction === "incoming";
          const toMyGroup = incoming && item.target_type === "group";
          return (
            <article key={item.request_id} className="su-card" style={{ padding: "1.1rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
                <div>
                  <span className="su-badge su-badge-soft">
                    {incoming ? "incoming" : "outgoing"}
                    {item.other_party.type === "group" || toMyGroup ? " · group" : ""}
                  </span>
                  <h3 style={{ margin: "0.55rem 0 0.25rem" }}>
                    {incoming
                      ? `${item.other_party.name ?? "Someone"}${toMyGroup ? ` → ${item.target.name ?? "your group"}` : ""}`
                      : `You → ${item.other_party.name ?? "them"}`}
                  </h3>
                  <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                    {eventNames[item.event_id] ?? "Event"} · {formatWhen(item.created_at, "")}
                  </p>
                  {item.message ? (
                    <p style={{ margin: "0.4rem 0 0", color: "var(--su-text-muted)" }}>“{item.message}”</p>
                  ) : null}
                </div>
                <span className={`su-badge ${STATUS_BADGE[item.status]}`}>{item.status}</span>
              </div>
              <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.9rem", flexWrap: "wrap" }}>
                {item.thread_id ? (
                  <Link className="su-btn su-btn-secondary" to={`/threads/${item.thread_id}`}>
                    Open chat
                  </Link>
                ) : null}
                {outcome && item.status === "accepted" ? (
                  <Link className="su-btn su-btn-secondary" to={outcome.to}>
                    {outcome.label}
                  </Link>
                ) : null}
                {pending && incoming ? (
                  <>
                    <button
                      type="button"
                      className="su-btn su-btn-primary"
                      disabled={busy !== null}
                      onClick={() => void respond(item, "accept")}
                    >
                      {busy === item.request_id ? "Working…" : "Accept"}
                    </button>
                    <button
                      type="button"
                      className="su-btn su-btn-secondary"
                      disabled={busy !== null}
                      onClick={() => void respond(item, "decline")}
                    >
                      Decline
                    </button>
                  </>
                ) : null}
                {pending && !incoming ? (
                  <button
                    type="button"
                    className="su-btn su-btn-secondary"
                    disabled={busy !== null}
                    onClick={() => void respond(item, "cancel")}
                  >
                    {busy === item.request_id ? "Working…" : "Cancel request"}
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

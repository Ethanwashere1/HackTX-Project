import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { RequestItem } from "../api/types";

export function RequestsPage() {
  const [items, setItems] = useState<RequestItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function load() {
    try {
      setItems(await api.listRequests());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function respond(id: string, action: "accept" | "decline") {
    const res = await api.respondRequest(id, action);
    if (action === "accept" && res.group_id) navigate(`/groups/${res.group_id}`);
    else await load();
  }

  if (error) return <div className="su-page">Error: {error}</div>;

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Requests</h1>
      <p className="su-page-sub">Mutual consent inbox — nothing forms until both sides say yes.</p>

      <div style={{ display: "grid", gap: "0.85rem", maxWidth: 820 }}>
        {items.map((item) => (
          <article key={item.request_id} className="su-card" style={{ padding: "1.1rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
              <div>
                <span className="su-badge su-badge-soft">{item.direction}</span>
                <h3 style={{ margin: "0.55rem 0 0.25rem" }}>{item.target_name}</h3>
                <p style={{ margin: 0, color: "var(--su-text-muted)" }}>{item.preview}</p>
              </div>
              <span className="su-badge su-badge-teal">{item.status}</span>
            </div>
            <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.9rem", flexWrap: "wrap" }}>
              {item.thread_id ? (
                <Link className="su-btn su-btn-secondary" to={`/threads/${item.thread_id}`}>
                  Open chat
                </Link>
              ) : null}
              {item.direction === "incoming" && item.status === "pending" ? (
                <>
                  <button
                    type="button"
                    className="su-btn su-btn-primary"
                    onClick={() => void respond(item.request_id, "accept")}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="su-btn su-btn-secondary"
                    onClick={() => void respond(item.request_id, "decline")}
                  >
                    Decline
                  </button>
                </>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Recommendation, RecommendationsResponse } from "../api/types";

export function RecommendationsPage() {
  const { eventId = "evt_hacktx" } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<RecommendationsResponse | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .recommendations(eventId)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [eventId]);

  async function request(rec: Recommendation) {
    setBusyId(rec.id);
    try {
      const res = await api.createRequest({
        target_type: rec.candidate_type,
        target_id: rec.id,
        event_id: eventId,
      });
      navigate(`/threads/${res.thread_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusyId(null);
    }
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!data) return <div className="su-page">Loading recommendations…</div>;

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">People and group recommendations</h1>
      <p className="su-page-sub">
        Ranked with reasons ({data.ranked_by}). Send a request — both sides must accept.
      </p>

      <div className="su-grid-2">
        {data.results.map((rec) => (
          <article key={rec.id} className="su-card" style={{ padding: "1.2rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
              <span className={`su-badge ${rec.candidate_type === "group" ? "su-badge-warm" : "su-badge-teal"}`}>
                {rec.candidate_type}
              </span>
              <span style={{ color: "var(--su-text-muted)", fontSize: "0.8rem" }}>
                {(rec.score * 100).toFixed(0)}% match
              </span>
            </div>
            <h3 style={{ margin: "0.75rem 0 0.25rem" }}>{rec.name}</h3>
            {rec.subtitle ? (
              <p style={{ margin: 0, color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
                {rec.subtitle}
                {rec.member_count ? ` · ${rec.member_count}` : ""}
              </p>
            ) : null}
            <p style={{ lineHeight: 1.55, color: "var(--su-text)" }}>{rec.reason}</p>
            {rec.tags?.length ? (
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.85rem" }}>
                {rec.tags.map((t) => (
                  <span key={t} className="su-badge su-badge-soft">
                    {t}
                  </span>
                ))}
              </div>
            ) : null}
            <button
              type="button"
              className="su-btn su-btn-primary"
              disabled={busyId === rec.id}
              onClick={() => void request(rec)}
            >
              {busyId === rec.id ? "Sending…" : "Request"}
            </button>
          </article>
        ))}
      </div>

      <p style={{ marginTop: "1.5rem" }}>
        <Link to="/requests">Open requests inbox →</Link>
      </p>
    </div>
  );
}

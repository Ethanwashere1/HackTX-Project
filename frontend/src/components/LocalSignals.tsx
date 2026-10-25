import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EnrichmentContext } from "../api/types";
import "./LocalSignals.css";

function readGeo(): Promise<{ lat: number; lng: number } | null> {
  if (!navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 5000, maximumAge: 60_000 },
    );
  });
}

export function LocalSignals() {
  const [data, setData] = useState<EnrichmentContext | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const geo = await readGeo();
        const ctx = await api.enrichmentContext({
          lat: geo?.lat ?? null,
          lng: geo?.lng ?? null,
          maps_q: "study spots cafes near UT Austin",
          calendar_q: "HackTX UT Austin campus events",
          social_kind: "github",
          social_handle: "mayachen",
        });
        if (!cancelled) setData(ctx);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Enrichment failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <aside className="signals su-card">
        <h3>Campus signals</h3>
        <p className="signals-muted">Couldn’t load Maps / calendar / social: {error}</p>
      </aside>
    );
  }

  if (!data) {
    return (
      <aside className="signals su-card">
        <h3>Campus signals</h3>
        <p className="signals-muted su-pulse">Pulling Maps, calendar, social & location…</p>
      </aside>
    );
  }

  const locLabel =
    data.location.lat != null && data.location.lng != null
      ? `${data.location.label} (${data.location.lat.toFixed(3)}, ${data.location.lng.toFixed(3)})`
      : `${data.location.label} · fallback ${data.location.fallback_lat}, ${data.location.fallback_lng}`;

  return (
    <aside className="signals su-card su-fade-up">
      <div className="signals-head">
        <h3>Campus signals</h3>
        <span className="su-badge su-badge-soft">
          {data.serpapi_configured || data.maps.source === "serpapi"
            ? "SerpAPI live"
            : "Demo data · removable"}
        </span>
      </div>
      <p className="signals-muted">
        Google Maps · Google Events · social search · your location via SerpAPI
      </p>

      <div className="signals-grid">
        <section>
          <h4>Your location</h4>
          <p>{locLabel}</p>
        </section>

        <section>
          <h4>Nearby (Maps)</h4>
          <ul>
            {data.maps.results.slice(0, 3).map((p) => (
              <li key={p.title}>
                {p.maps_url ? (
                  <a href={p.maps_url} target="_blank" rel="noreferrer">
                    {p.title}
                  </a>
                ) : (
                  p.title
                )}
                {p.address ? <span> — {p.address}</span> : null}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4>Calendar / events</h4>
          <ul>
            {data.calendar.results.slice(0, 3).map((e) => (
              <li key={e.title}>
                <strong>{e.title}</strong>
                {e.date ? <span> · {e.date}</span> : null}
                {e.venue ? <span> · {e.venue}</span> : null}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4>Social</h4>
          <p>
            <strong>{data.social.result.kind}</strong>/{data.social.result.handle}
            {data.social.result.bio ? ` — ${data.social.result.bio}` : null}
          </p>
        </section>
      </div>
    </aside>
  );
}

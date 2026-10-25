import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Contact, Profile } from "../api/types";

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [discord, setDiscord] = useState("");
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .getProfile()
      .then((p) => {
        setProfile(p);
        setDiscord(p.contacts.find((c) => c.kind === "discord")?.value ?? "");
        setPhone(p.contacts.find((c) => c.kind === "phone")?.value ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    const contacts: Contact[] = [];
    if (discord.trim()) contacts.push({ kind: "discord", value: discord.trim() });
    if (phone.trim()) contacts.push({ kind: "phone", value: phone.trim() });
    try {
      await api.saveContacts(contacts);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!profile) return <div className="su-page">Loading profile…</div>;

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">{profile.name}</h1>
      <p className="su-page-sub">{profile.email} · contact methods stay private until mutual accept</p>

      {profile.summary ? (
        <article className="su-card" style={{ padding: "1.15rem", marginBottom: "1rem", maxWidth: 720 }}>
          <h3>Interview summary</h3>
          <p style={{ lineHeight: 1.55 }}>{profile.summary}</p>
          {profile.traits ? (
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              {Object.entries(profile.traits).map(([k, v]) => (
                <span key={k} className="su-badge su-badge-soft">
                  {k}: {v}
                </span>
              ))}
            </div>
          ) : null}
        </article>
      ) : null}

      <form className="su-card" style={{ padding: "1.15rem", maxWidth: 720 }} onSubmit={(e) => void onSave(e)}>
        <h3>Contact methods</h3>
        <div className="su-field">
          <label className="su-label">Discord</label>
          <input className="su-input" value={discord} onChange={(e) => setDiscord(e.target.value)} />
        </div>
        <div className="su-field">
          <label className="su-label">Phone</label>
          <input className="su-input" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <h3>Socials</h3>
        <ul style={{ color: "var(--su-text-muted)" }}>
          {profile.socials.map((s) => (
            <li key={`${s.kind}-${s.value}`}>
              {s.kind}: {s.value}
            </li>
          ))}
        </ul>
        <button className="su-btn su-btn-primary" type="submit">
          Save contacts
        </button>
        {saved ? <p style={{ color: "var(--su-success)" }}>Saved.</p> : null}
      </form>
    </div>
  );
}

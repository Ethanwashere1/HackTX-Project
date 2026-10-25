import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { traitBadges } from "../api/format";
import type { Contact, Profile } from "../api/types";

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [discord, setDiscord] = useState("");
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getProfile()
      .then((p) => {
        setProfile(p);
        setDiscord(p.contacts.find((c) => c.kind === "discord")?.value ?? "");
        setPhone(p.contacts.find((c) => c.kind === "phone")?.value ?? "");
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setSaved(false);
    setSaveError(null);
    // PUT /api/me/contacts replaces the whole list: keep the kinds this form doesn't edit.
    const contacts: Contact[] = profile.contacts.filter((c) => c.kind !== "discord" && c.kind !== "phone");
    if (discord.trim()) contacts.push({ kind: "discord", value: discord.trim() });
    if (phone.trim()) contacts.push({ kind: "phone", value: phone.trim() });
    try {
      const saved = await api.saveContacts(contacts);
      setProfile({ ...profile, contacts: saved });
      setSaved(true);
    } catch (err) {
      setSaveError(errorMessage(err, "Save failed"));
    }
  }

  if (error) return <div className="su-page">Error: {error}</div>;
  if (!profile) return <div className="su-page">Loading profile…</div>;

  const badges = traitBadges(profile.traits);
  const otherContacts = profile.contacts.filter((c) => c.kind !== "discord" && c.kind !== "phone");

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">{profile.name}</h1>
      <p className="su-page-sub">{profile.email} · contact methods stay private until mutual accept</p>

      <article className="su-card" style={{ padding: "1.15rem", marginBottom: "1rem", maxWidth: 720 }}>
        <h3>Interview summary</h3>
        {profile.interviewed && profile.summary ? (
          <>
            <p style={{ lineHeight: 1.55 }}>{profile.summary}</p>
            {badges.length ? (
              <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                {badges.map((b) => (
                  <span key={b} className="su-badge su-badge-soft">
                    {b}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <p style={{ color: "var(--su-text-muted)" }}>
            No interview yet. Take the optional voice intro from an event to add a summary to your
            profile.
          </p>
        )}
      </article>

      <form className="su-card" style={{ padding: "1.15rem", maxWidth: 720 }} onSubmit={(e) => void onSave(e)}>
        <h3>Contact methods</h3>
        <div className="su-field">
          <label className="su-label" htmlFor="discord">
            Discord
          </label>
          <input id="discord" className="su-input" maxLength={300} value={discord} onChange={(e) => setDiscord(e.target.value)} />
        </div>
        <div className="su-field">
          <label className="su-label" htmlFor="phone">
            Phone
          </label>
          <input id="phone" className="su-input" maxLength={300} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        {otherContacts.length ? (
          <ul style={{ color: "var(--su-text-muted)" }}>
            {otherContacts.map((c) => (
              <li key={`${c.kind}-${c.value}`}>
                {c.kind}: {c.value}
              </li>
            ))}
          </ul>
        ) : null}
        <h3>Socials</h3>
        {profile.socials.length ? (
          <ul style={{ color: "var(--su-text-muted)" }}>
            {profile.socials.map((s) => (
              <li key={`${s.kind}-${s.value}`}>
                {s.kind}: {s.value}
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ color: "var(--su-text-muted)" }}>Add socials when you join an event.</p>
        )}
        <button className="su-btn su-btn-primary" type="submit">
          Save contacts
        </button>
        {saved ? <p style={{ color: "var(--su-success)" }}>Saved.</p> : null}
        {saveError ? <p style={{ color: "var(--su-danger)" }}>{saveError}</p> : null}
      </form>
    </div>
  );
}

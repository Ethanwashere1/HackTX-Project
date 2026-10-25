import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EventDetail } from "../api/types";

export function JoinEventPage() {
  const { eventId = "evt_hacktx" } = useParams();
  const navigate = useNavigate();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [skills, setSkills] = useState("react, figma");
  const [experience, setExperience] = useState("intermediate");
  const [subjects, setSubjects] = useState("discrete math");
  const [github, setGithub] = useState("mayachen");
  const [instagram, setInstagram] = useState("@maya.builds");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.getEvent(eventId).then(setEvent).catch((e: Error) => setError(e.message));
  }, [eventId]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!event) return;
    setBusy(true);
    setError(null);
    try {
      const fields =
        event.type === "structured"
          ? {
              skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
              experience_level: experience,
            }
          : { subjects };
      const res = await api.joinEvent(eventId, {
        answers: event.questions.map((q) => ({
          question_id: q.question_id,
          value: answers[q.question_id] ?? "",
        })),
        fields,
        socials: [
          { kind: "github", value: github },
          { kind: "instagram", value: instagram },
        ],
      });
      if (res.interview.available) navigate(`/events/${eventId}/interview`);
      else navigate(`/events/${eventId}/recommendations`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Join failed");
    } finally {
      setBusy(false);
    }
  }

  if (!event) return <div className="su-page">{error ?? "Loading…"}</div>;

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Join {event.name}</h1>
      <p className="su-page-sub">Answer a few questions so matching has something real to work with.</p>

      <form className="su-card" style={{ padding: "1.25rem", maxWidth: 720 }} onSubmit={(e) => void onSubmit(e)}>
        {event.questions.map((q) => (
          <div className="su-field" key={q.question_id}>
            <label className="su-label" htmlFor={q.question_id}>
              {q.text}
              {q.required ? " *" : ""}
            </label>
            {q.kind === "single_choice" && q.options ? (
              <select
                id={q.question_id}
                className="su-select"
                required={q.required}
                value={answers[q.question_id] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
              >
                <option value="">Select…</option>
                {q.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={q.question_id}
                className="su-input"
                required={q.required}
                value={answers[q.question_id] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
              />
            )}
          </div>
        ))}

        {event.type === "structured" ? (
          <>
            <div className="su-field">
              <label className="su-label">Skills</label>
              <input className="su-input" value={skills} onChange={(e) => setSkills(e.target.value)} />
            </div>
            <div className="su-field">
              <label className="su-label">Experience level</label>
              <input
                className="su-input"
                value={experience}
                onChange={(e) => setExperience(e.target.value)}
              />
            </div>
          </>
        ) : (
          <div className="su-field">
            <label className="su-label">Subjects</label>
            <input className="su-input" value={subjects} onChange={(e) => setSubjects(e.target.value)} />
          </div>
        )}

        <div className="su-grid-2">
          <div className="su-field">
            <label className="su-label">GitHub</label>
            <input className="su-input" value={github} onChange={(e) => setGithub(e.target.value)} />
          </div>
          <div className="su-field">
            <label className="su-label">Instagram</label>
            <input
              className="su-input"
              value={instagram}
              onChange={(e) => setInstagram(e.target.value)}
            />
          </div>
        </div>

        {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}
        <button className="su-btn su-btn-primary" type="submit" disabled={busy}>
          {busy ? "Joining…" : "Continue"}
        </button>
      </form>
    </div>
  );
}

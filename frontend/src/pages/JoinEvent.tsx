import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import type { AnswerValue, Contact, ContactKind, EventDetail, FieldValue, Question } from "../api/types";

const SOCIAL_KINDS: { kind: ContactKind; label: string; placeholder: string }[] = [
  { kind: "github", label: "GitHub", placeholder: "username" },
  { kind: "linkedin", label: "LinkedIn", placeholder: "linkedin.com/in/…" },
  { kind: "instagram", label: "Instagram", placeholder: "@handle" },
];

function humanize(key: string) {
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** The answer value the contract expects for the question kind, or null if unanswered. */
function answerValue(q: Question, raw: string | string[] | undefined): AnswerValue | null {
  if (raw === undefined) return null;
  if (q.kind === "multi_choice") return Array.isArray(raw) && raw.length ? raw : null;
  const text = (Array.isArray(raw) ? raw.join(", ") : raw).trim();
  if (!text) return null;
  if (q.kind === "number") {
    const n = Number(text);
    return Number.isFinite(n) ? n : null;
  }
  return text;
}

/** A field with commas becomes a list of strings ("react, figma"), otherwise a string. */
function fieldValue(raw: string): FieldValue | null {
  const text = raw.trim();
  if (!text) return null;
  if (text.includes(",")) {
    const list = text.split(",").map((s) => s.trim()).filter(Boolean);
    return list.length ? list : null;
  }
  return text;
}

export function JoinEventPage() {
  const { eventId = "" } = useParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const [socials, setSocials] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getEvent(eventId)
      .then(setEvent)
      .catch((e: unknown) => setError(errorMessage(e)));
  }, [eventId]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!event) return;
    setBusy(true);
    setError(null);
    try {
      const answerList = event.questions.flatMap((q) => {
        const value = answerValue(q, answers[q.question_id]);
        return value === null ? [] : [{ question_id: q.question_id, value }];
      });
      const fieldMap: Record<string, FieldValue> = {};
      for (const key of event.required_fields) {
        const value = fieldValue(fields[key] ?? "");
        if (value !== null) fieldMap[key] = value;
      }
      const socialList: Contact[] = SOCIAL_KINDS.flatMap(({ kind }) => {
        const value = (socials[kind] ?? "").trim();
        return value ? [{ kind, value }] : [];
      });
      const res = await api.joinEvent(eventId, {
        answers: answerList,
        fields: fieldMap,
        socials: socialList,
      });
      if (res.interview.available) navigate(`/events/${eventId}/interview`);
      else navigate(`/events/${eventId}/recommendations`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_joined") {
        navigate(`/events/${eventId}`);
        return;
      }
      setError(errorMessage(err, "Join failed"));
    } finally {
      setBusy(false);
    }
  }

  if (!event) return <div className="su-page">{error ?? "Loading…"}</div>;

  if (event.my_membership) {
    return (
      <div className="su-page su-fade-up">
        <h1 className="su-page-title">You're in {event.name}</h1>
        <Link className="su-btn su-btn-primary" to={`/events/${event.event_id}/recommendations`}>
          See recommendations
        </Link>
      </div>
    );
  }

  const setAnswer = (id: string, v: string | string[]) => setAnswers({ ...answers, [id]: v });

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Join {event.name}</h1>
      <p className="su-page-sub">
        Answer {event.questions.length} question{event.questions.length === 1 ? "" : "s"} so matching
        has something real to work with.
      </p>

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
                value={(answers[q.question_id] as string | undefined) ?? ""}
                onChange={(e) => setAnswer(q.question_id, e.target.value)}
              >
                <option value="">Select…</option>
                {q.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : q.kind === "multi_choice" && q.options ? (
              <div id={q.question_id} style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                {q.options.map((o) => {
                  const picked = (answers[q.question_id] as string[] | undefined) ?? [];
                  return (
                    <label key={o} style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                      <input
                        type="checkbox"
                        checked={picked.includes(o)}
                        onChange={(e) =>
                          setAnswer(
                            q.question_id,
                            e.target.checked ? [...picked, o] : picked.filter((x) => x !== o),
                          )
                        }
                      />
                      {o}
                    </label>
                  );
                })}
              </div>
            ) : (
              <input
                id={q.question_id}
                className="su-input"
                type={q.kind === "number" ? "number" : "text"}
                maxLength={q.kind === "text" ? 2000 : undefined}
                required={q.required}
                value={(answers[q.question_id] as string | undefined) ?? ""}
                onChange={(e) => setAnswer(q.question_id, e.target.value)}
              />
            )}
          </div>
        ))}

        {event.required_fields.map((key) => (
          <div className="su-field" key={key}>
            <label className="su-label" htmlFor={`field-${key}`}>
              {humanize(key)} *
            </label>
            <input
              id={`field-${key}`}
              className="su-input"
              required
              maxLength={500}
              placeholder="Separate several with commas"
              value={fields[key] ?? ""}
              onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
            />
          </div>
        ))}

        <div className="su-grid-2">
          {SOCIAL_KINDS.map((s) => (
            <div className="su-field" key={s.kind}>
              <label className="su-label" htmlFor={`social-${s.kind}`}>
                {s.label} (optional)
              </label>
              <input
                id={`social-${s.kind}`}
                className="su-input"
                maxLength={300}
                placeholder={s.placeholder}
                value={socials[s.kind] ?? ""}
                onChange={(e) => setSocials({ ...socials, [s.kind]: e.target.value })}
              />
            </div>
          ))}
        </div>

        {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}
        <button className="su-btn su-btn-primary" type="submit" disabled={busy}>
          {busy ? "Joining…" : "Continue"}
        </button>
      </form>
    </div>
  );
}

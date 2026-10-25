import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import type { CreateEventBody, EventType, QuestionKind, Tone } from "../api/types";
import { useAuth } from "../auth/AuthContext";

type DraftQ = { text: string; kind: QuestionKind; options: string; required: boolean };

/** "Experience level, skills" -> ["experience_level", "skills"] (contract: ^[a-z][a-z0-9_]{0,49}$). */
function fieldKeys(raw: string): string[] {
  const keys = raw
    .split(",")
    .map((s) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""))
    .filter((k) => /^[a-z][a-z0-9_]{0,49}$/.test(k));
  return [...new Set(keys)];
}

export function CreateEventPage() {
  const navigate = useNavigate();
  const { me } = useAuth();
  const [params] = useSearchParams();
  const myOrgs = me?.orgs ?? [];
  const [orgId, setOrgId] = useState<string>(params.get("org") ?? myOrgs[0]?.org_id ?? "");
  const [name, setName] = useState("HackTX team-up");
  const [description, setDescription] = useState("Find your hackathon team");
  const [type, setType] = useState<EventType>("structured");
  const [tone, setTone] = useState<Tone>("casual");
  const [groupCount, setGroupCount] = useState(6);
  const [minSize, setMinSize] = useState(3);
  const [maxSize, setMaxSize] = useState(4);
  const [maxGroupsPerUser, setMaxGroupsPerUser] = useState(1);
  const [requiredFields, setRequiredFields] = useState("skills, experience_level");
  const [startsAt, setStartsAt] = useState("");
  const [interview, setInterview] = useState(true);
  const [questions, setQuestions] = useState<DraftQ[]>(DEFAULT_QUESTIONS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setQuestionCount(count: number) {
    setQuestions((prev) => resizeQuestions(prev, count));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: CreateEventBody = {
        name,
        description,
        type,
        tone,
        interview_enabled: interview,
        required_fields: fieldKeys(requiredFields),
        questions: questions
          .filter((q) => q.text.trim())
          .map((q) => ({
            text: q.text.trim(),
            kind: q.kind,
            required: q.required,
            options:
              q.kind === "single_choice" || q.kind === "multi_choice"
                ? [...new Set(q.options.split(",").map((s) => s.trim()).filter(Boolean))]
                : null,
          })),
      };
      // Without an org the event is unlisted and reachable by link only.
      if (orgId) body.org_id = orgId;
      if (startsAt) body.starts_at = new Date(startsAt).toISOString();
      // Informal events must omit the group settings (422 otherwise).
      if (type === "structured") {
        body.group_count = groupCount;
        body.min_size = minSize;
        body.max_size = maxSize;
        body.max_groups_per_user = maxGroupsPerUser;
      }
      const res = await api.createEvent(body);
      navigate(`/events/${res.event_id}`);
    } catch (err) {
      setError(errorMessage(err, "Failed to create event"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="su-page su-fade-up">
      <h1 className="su-page-title">Create event</h1>
      <p className="su-page-sub">Host a structured squad-up or an informal 1:1 connection event.</p>

      <form className="su-card" style={{ padding: "1.25rem", maxWidth: 720 }} onSubmit={(e) => void onSubmit(e)}>
        <div className="su-field">
          <label className="su-label" htmlFor="org">
            Organization
          </label>
          <select id="org" className="su-select" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
            {myOrgs.map((o) => (
              <option key={o.org_id} value={o.org_id}>
                {o.name} (members only)
              </option>
            ))}
            <option value="">No organization (unlisted, anyone with the link)</option>
          </select>
        </div>
        <div className="su-field">
          <label className="su-label" htmlFor="name">
            Event name
          </label>
          <input id="name" className="su-input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="su-field">
          <label className="su-label" htmlFor="desc">
            Description
          </label>
          <textarea
            id="desc"
            className="su-textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="su-grid-2">
          <div className="su-field">
            <label className="su-label" htmlFor="type">
              Type
            </label>
            <select
              id="type"
              className="su-select"
              value={type}
              onChange={(e) => setType(e.target.value as EventType)}
            >
              <option value="structured">Structured (squads)</option>
              <option value="informal">Informal (1:1)</option>
            </select>
          </div>
          <div className="su-field">
            <label className="su-label" htmlFor="tone">
              Tone
            </label>
            <select
              id="tone"
              className="su-select"
              value={tone}
              onChange={(e) => setTone(e.target.value as Tone)}
            >
              <option value="casual">Casual</option>
              <option value="professional">Professional</option>
            </select>
          </div>
        </div>

        {type === "structured" ? (
          <div className="su-grid-2">
            <div className="su-field">
              <label className="su-label">Max groups per person</label>
              <input
                className="su-input"
                type="number"
                min={1}
                value={maxGroupsPerUser}
                onChange={(e) => setMaxGroupsPerUser(Number(e.target.value))}
              />
            </div>
            <div className="su-field">
              <label className="su-label">Group count</label>
              <input
                className="su-input"
                type="number"
                min={1}
                value={groupCount}
                onChange={(e) => setGroupCount(Number(e.target.value))}
              />
            </div>
            <div className="su-field">
              <label className="su-label">Min / max squad size</label>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <input
                  className="su-input"
                  type="number"
                  min={1}
                  value={minSize}
                  onChange={(e) => setMinSize(Number(e.target.value))}
                />
                <input
                  className="su-input"
                  type="number"
                  min={1}
                  value={maxSize}
                  onChange={(e) => setMaxSize(Number(e.target.value))}
                />
              </div>
            </div>
          </div>
        ) : null}

        <div className="su-grid-2">
          <div className="su-field">
            <label className="su-label" htmlFor="fields">
              Profile fields everyone fills in (comma-separated)
            </label>
            <input
              id="fields"
              className="su-input"
              value={requiredFields}
              placeholder="skills, experience_level"
              onChange={(e) => setRequiredFields(e.target.value)}
            />
          </div>
          <div className="su-field">
            <label className="su-label" htmlFor="starts">
              Starts at (optional)
            </label>
            <input
              id="starts"
              className="su-input"
              type="datetime-local"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
            />
          </div>
        </div>

        <label className="su-label" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input type="checkbox" checked={interview} onChange={(e) => setInterview(e.target.checked)} />
          Enable optional voice interview
        </label>

        <div
          style={{
            marginTop: "1.5rem",
            display: "flex",
            justifyContent: "space-between",
            gap: "1rem",
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          <h3 style={{ margin: 0 }}>Questionnaire</h3>
          <div className="su-field" style={{ marginBottom: 0, minWidth: 160 }}>
            <label className="su-label" htmlFor="q-count">
              Number of questions
            </label>
            <input
              id="q-count"
              className="su-input"
              type="number"
              min={0}
              max={MAX_QUESTIONS}
              value={questions.length}
              onChange={(e) => setQuestionCount(Number(e.target.value))}
            />
          </div>
        </div>
        <p style={{ margin: "0.35rem 0 1rem", color: "var(--su-text-muted)", fontSize: "0.85rem" }}>
          Set how many questions joiners answer (0–{MAX_QUESTIONS}). Add, remove, or edit each one below.
        </p>

        {questions.map((q, i) => (
          <div key={i} className="su-card" style={{ padding: "0.9rem", marginBottom: "0.75rem", boxShadow: "none" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" }}>
              <strong style={{ fontSize: "0.85rem" }}>Question {i + 1}</strong>
              <button
                type="button"
                className="su-btn su-btn-ghost"
                onClick={() => setQuestions(questions.filter((_, idx) => idx !== i))}
              >
                Remove
              </button>
            </div>
            <div className="su-field">
              <label className="su-label">Prompt</label>
              <input
                className="su-input"
                value={q.text}
                onChange={(e) => {
                  const next = [...questions];
                  next[i] = { ...q, text: e.target.value };
                  setQuestions(next);
                }}
              />
            </div>
            <div className="su-grid-2">
              <div className="su-field">
                <label className="su-label">Kind</label>
                <select
                  className="su-select"
                  value={q.kind}
                  onChange={(e) => {
                    const next = [...questions];
                    next[i] = { ...q, kind: e.target.value as QuestionKind };
                    setQuestions(next);
                  }}
                >
                  <option value="text">Text</option>
                  <option value="single_choice">Single choice</option>
                  <option value="multi_choice">Multi choice</option>
                  <option value="number">Number</option>
                </select>
              </div>
              <div className="su-field">
                <label className="su-label">Options (comma-separated)</label>
                <input
                  className="su-input"
                  value={q.options}
                  disabled={q.kind === "text" || q.kind === "number"}
                  onChange={(e) => {
                    const next = [...questions];
                    next[i] = { ...q, options: e.target.value };
                    setQuestions(next);
                  }}
                />
              </div>
            </div>
            <label className="su-label" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <input
                type="checkbox"
                checked={q.required}
                onChange={(e) => {
                  const next = [...questions];
                  next[i] = { ...q, required: e.target.checked };
                  setQuestions(next);
                }}
              />
              Required
            </label>
          </div>
        ))}

        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className="su-btn su-btn-secondary"
            disabled={questions.length >= MAX_QUESTIONS}
            onClick={() => setQuestions([...questions, { ...EMPTY_Q }])}
          >
            + Add question
          </button>
          {questions.length > 0 ? (
            <button
              type="button"
              className="su-btn su-btn-ghost"
              onClick={() => setQuestionCount(questions.length - 1)}
            >
              − Remove last
            </button>
          ) : null}
        </div>

        {error ? <p style={{ color: "var(--su-danger)" }}>{error}</p> : null}

        <div style={{ marginTop: "1.25rem" }}>
          <button className="su-btn su-btn-primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create event"}
          </button>
        </div>
      </form>
    </div>
  );
}

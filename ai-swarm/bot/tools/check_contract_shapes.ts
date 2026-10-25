import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineTool } from "@grok/agent-sdk/tools";
import * as z from "zod/v4";

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const AGENTS_DIR = path.join(REPO_ROOT, "agents");

const SCRIPT = `
import json, os, sys
os.environ.setdefault("GEMINI_API_KEY", "REPLACE_ME")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ.setdefault("BACKEND_URL", "http://backend.test")
from fastapi.testclient import TestClient
import agents, main

AUTH = {"X-Internal-Key": "test-internal-key"}
results = []

def record(name, ok, detail):
    results.append({"check": name, "ok": ok, "detail": detail})

# Fake Gemini client so endpoints do not 503
class FakeResp:
    def __init__(self, text): self.text = text
class FakeModels:
    def generate_content(self, **kwargs):
        schema = kwargs["config"].response_schema
        name = getattr(schema, "__name__", "")
        if name == "RecommenderResponse":
            return FakeResp(json.dumps({"results": [{"id": "usr_b2", "score": 0.87, "reason": "Shared climate topics."}]}))
        if name == "ProfileOverviewResponse":
            return FakeResp(json.dumps({"overview": "Climate frontend builder.", "traits": {"topics": "climate", "group_need": "hackathon teammates"}}))
        if name == "QuizGenResponse":
            return FakeResp(json.dumps({"questions": [{"text": "Hours this weekend?", "kind": "single_choice", "options": ["under 8", "all weekend"], "required": True}]}))
        return FakeResp("{}")
class FakeClient:
    def __init__(self):
        self.models = FakeModels()
agents._client = FakeClient()

client = TestClient(main.app)

# health
r = client.get("/health")
record("GET /health", r.status_code == 200 and r.json() == {"ok": True, "service": "agents"}, r.text[:200])

# recommend
body = {
  "event": {"event_id": "evt_h1", "type": "structured", "tone": "casual", "description": "x"},
  "viewer": {"user_id": "usr_a1", "profile_text": "frontend", "traits": {"topics": "climate"}, "topic_signals": ["climate"], "group_need": "team"},
  "candidates": [{"candidate_type": "user", "id": "usr_b2", "profile_text": "backend", "similarity": 0.8, "topic_signals": ["climate"], "group_need": "team"}],
  "limit": 5,
}
r = client.post("/recommend", json=body, headers=AUTH)
ok = r.status_code == 200 and "results" in r.json() and r.json()["results"][0]["id"] == "usr_b2"
record("POST /recommend", ok, r.text[:300])

# profile-overview
ov = {
  "user": {"user_id": "usr_a1", "name": "Ana"},
  "answers": {"q_1": "frontend"},
  "fields": {"skills": ["react"]},
  "social_notes": "",
  "interview_summary": "Pairs well",
  "interview_traits": {"working_style": "pairing"},
}
r = client.post("/profile-overview", json=ov, headers=AUTH)
ok = r.status_code == 200 and "overview" in r.json() and "traits" in r.json()
record("POST /profile-overview", ok, r.text[:300])

# generate-questions
gq = {
  "event": {"name": "HackTX", "type": "structured", "tone": "casual", "description": "teams"},
  "existing_questions": [],
  "count": 1,
  "hint": "availability",
}
r = client.post("/generate-questions", json=gq, headers=AUTH)
ok = r.status_code == 200 and isinstance(r.json().get("questions"), list) and r.json()["questions"]
record("POST /generate-questions", ok, r.text[:300])

# auth gate
r = client.post("/recommend", json=body)
record("POST /recommend auth", r.status_code == 401, r.text[:200])

print(json.dumps({"all_ok": all(x["ok"] for x in results), "checks": results}))
`;

export default defineTool({
  description:
    "Check agents HTTP contract shapes for /health, /recommend, /profile-overview, and /generate-questions using the FastAPI TestClient and a fake Gemini client (no network).",
  effect: "read",
  inputSchema: z.object({}),
  async execute() {
    const result = await new Promise<{
      code: number | null;
      stdout: string;
      stderr: string;
    }>((resolve) => {
      const child = spawn("uv", ["run", "python", "-c", SCRIPT], {
        cwd: AGENTS_DIR,
        env: process.env,
      });
      let stdout = "";
      let stderr = "";
      const timer = setTimeout(() => child.kill("SIGKILL"), 120_000);
      child.stdout.on("data", (c: Buffer) => {
        stdout += c.toString();
      });
      child.stderr.on("data", (c: Buffer) => {
        stderr += c.toString();
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        resolve({ code, stdout, stderr });
      });
      child.on("error", (err) => {
        clearTimeout(timer);
        resolve({ code: 1, stdout, stderr: err.message });
      });
    });

    type ShapeCheck = { check: string; ok: boolean; detail: string };
    type ShapeReport = { all_ok?: boolean; checks?: ShapeCheck[] };
    let parsed: ShapeReport | null = null;
    try {
      const line = result.stdout
        .trim()
        .split("\n")
        .filter(Boolean)
        .at(-1);
      parsed = line ? (JSON.parse(line) as ShapeReport) : null;
    } catch {
      parsed = null;
    }

    const checks: ShapeCheck[] = Array.isArray(parsed?.checks)
      ? parsed!.checks!
      : [];

    return {
      ok: result.code === 0 && Boolean(parsed?.all_ok),
      exitCode: result.code ?? 1,
      checkCount: checks.length,
      checks,
      stderr:
        result.stderr.length > 4000
          ? `${result.stderr.slice(0, 4000)}\n…[truncated]\n`
          : result.stderr,
      stdout:
        result.stdout.length > 4000
          ? `${result.stdout.slice(0, 4000)}\n…[truncated]\n`
          : result.stdout,
    };
  },
});

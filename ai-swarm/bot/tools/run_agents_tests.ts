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

function run(
  command: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd,
      env: process.env,
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
    }, timeoutMs);
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: 1, stdout, stderr: `${stderr}\n${err.message}` });
    });
  });
}

export default defineTool({
  description:
    "Run the SquadUp agents/ pytest suite with mocked Gemini (no network). Returns pass/fail, summary lines, and truncated output.",
  effect: "read",
  inputSchema: z.object({
    extraArgs: z
      .array(z.string())
      .optional()
      .describe("Optional extra pytest args, e.g. ['tests/test_http.py', '-k', 'recommend']"),
  }),
  async execute({ extraArgs }) {
    const args = ["run", "pytest", "-q", ...(extraArgs ?? [])];
    const result = await run("uv", args, AGENTS_DIR, 180_000);
    const combined = `${result.stdout}\n${result.stderr}`.trim();
    const truncated =
      combined.length > 12_000
        ? `${combined.slice(0, 12_000)}\n…[truncated]\n`
        : combined;
    const passed = result.code === 0;
    return {
      ok: passed,
      exitCode: result.code,
      cwd: AGENTS_DIR,
      command: `uv ${args.join(" ")}`,
      summary: passed
        ? "agents pytest green (mocked Gemini)"
        : "agents pytest failed — inspect output",
      output: truncated,
    };
  },
});

import {
  defaultGitHubPullRequestDispatch,
  githubChannel,
} from "@grok/agent-sdk/channels/github";

const MAX_DIFF_CHARS = 150_000;
const AGENTS_PREFIX = "agents/";

function isAgentsPath(path: string): boolean {
  return path === "agents" || path.startsWith(AGENTS_PREFIX);
}

export default githubChannel({
  botName: "ai-swarm",
  credentials: {
    webhookSecret: { secretName: "GITHUB_WEBHOOK_SECRET" },
    token: { secretName: "GITHUB_TOKEN" },
  },
  deliverReplies: false,
  onComment: () => null,
  onPullRequest: (ctx, pr) => {
    if (pr.draft) {
      return null;
    }
    const dispatch = defaultGitHubPullRequestDispatch(ctx, pr);
    if (dispatch === null) {
      return null;
    }
    return {
      auth: dispatch.auth,
      context: [
        "Review SquadUp product AI under agents/ only.",
        "Ignore backend/ and frontend/ changes.",
        "If pr/skip.txt is present, reply that there is nothing to review and stop.",
        "Use agents-harness, matchmaker-recommend, profiler-overview, quizgen-questions, interviewer-qa as needed.",
        "Check fallbacks: similarity recs, null overview, quiz 502, gemini_not_configured.",
        "Read pr/diff.patch when present.",
      ],
      async workspaceFiles(): Promise<Record<string, string>> {
        const octokit = await ctx.github.getOctokit();
        const diff = await octokit.rest.pulls.get({
          owner: ctx.repository.owner,
          repo: ctx.repository.name,
          pull_number: pr.number,
          mediaType: { format: "diff" },
        });
        const text = typeof diff.data === "string" ? diff.data : "";
        const mentionsAgents =
          text.includes(`a/${AGENTS_PREFIX}`) ||
          text.includes(`b/${AGENTS_PREFIX}`) ||
          text.split("\n").some((line) => {
            if (!line.startsWith("+++ ") && !line.startsWith("--- ")) {
              return false;
            }
            const path = line
              .replace(/^\+\+\+ |\-\-\- /, "")
              .replace(/^[ab]\//, "");
            return isAgentsPath(path);
          });

        const files: Record<string, string> = {
          "pr/head.sha": pr.headSha,
        };
        if (!mentionsAgents) {
          files["pr/skip.txt"] = "No agents/ paths in this PR diff.";
          return files;
        }
        files["pr/diff.patch"] =
          text.length > MAX_DIFF_CHARS
            ? `${text.slice(0, MAX_DIFF_CHARS)}\n…[truncated]\n`
            : text;
        return files;
      },
    };
  },
});

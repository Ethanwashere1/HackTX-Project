import {
  defaultGitHubPullRequestDispatch,
  githubChannel,
} from "@grok/agent-sdk/channels/github";

const MAX_DIFF_CHARS = 150_000;
const FRONTEND_PREFIX = "frontend/";

function isFrontendPath(path: string): boolean {
  return path === "frontend" || path.startsWith(FRONTEND_PREFIX);
}

// Named secrets (env locally / deployment secrets on hosting).
// For Cursor-managed SCM events after login, you can switch to
// cursorAccount: { repos: ["Ethanwashere1/HackTX-Project"], permissions: "pr-write" }.
export default githubChannel({
  botName: "uiux-swarm",
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
        "Review UI/UX for SquadUp frontend only.",
        "Ignore backend/ and agents/ changes.",
        "If pr/skip.txt is present, reply that there is nothing to review and stop.",
        "Use a11y-critique and layout specialists; post findings as a concise critique, not a backend review.",
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
        const mentionsFrontend =
          text.includes(`a/${FRONTEND_PREFIX}`) ||
          text.includes(`b/${FRONTEND_PREFIX}`) ||
          text.split("\n").some((line) => {
            if (!line.startsWith("+++ ") && !line.startsWith("--- ")) {
              return false;
            }
            const path = line.replace(/^\+\+\+ |\-\-\- /, "").replace(/^[ab]\//, "");
            return isFrontendPath(path);
          });

        const files: Record<string, string> = {
          "pr/head.sha": pr.headSha,
        };
        if (!mentionsFrontend) {
          files["pr/skip.txt"] = "No frontend/ paths in this PR diff.";
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

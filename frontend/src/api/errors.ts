import type { ApiErrorBody } from "./types";

/** A non-2xx API response. `code` is the contract's `error.code` (e.g. `not_org_member`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  static async fromResponse(res: Response): Promise<ApiError> {
    let body: Partial<ApiErrorBody> | null = null;
    try {
      body = (await res.json()) as Partial<ApiErrorBody>;
    } catch {
      /* not JSON */
    }
    return new ApiError(
      res.status,
      body?.error?.code ?? `http_${res.status}`,
      body?.error?.message ?? `Request failed (${res.status})`,
    );
  }
}

export function errorCode(e: unknown): string | null {
  return e instanceof ApiError ? e.code : null;
}

/** Friendly copy for the error codes the UI shows inline; falls back to the server message. */
const FRIENDLY: Record<string, string> = {
  unauthenticated: "Your session expired. Sign in again.",
  not_org_member: "This belongs to an organization you haven't joined yet.",
  not_org_admin: "Only org admins can do that.",
  already_joined: "You already joined this event.",
  already_member: "You're already a member of this organization.",
  already_in_group: "You're already in a group together.",
  already_connected: "You're already connected.",
  duplicate_request: "You already have a pending request to them.",
  group_full: "That group is already full.",
  group_limit_reached: "This event already has all its groups.",
  group_limit_per_user: "That would put someone in more groups than this event allows.",
  request_not_pending: "That request was already handled.",
  interview_disabled: "This event has no interview.",
};

export function errorMessage(e: unknown, fallback = "Something went wrong"): string {
  if (e instanceof ApiError) {
    // invalid_answers / validation_error messages carry the detail the user needs to fix.
    if (e.code === "invalid_answers" || e.code === "validation_error") return e.message;
    return FRIENDLY[e.code] ?? e.message;
  }
  if (e instanceof Error) return e.message;
  return fallback;
}

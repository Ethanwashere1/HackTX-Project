// Shapes from docs/CONTRACT.md (v1.0-pre.7) and the backend serializers (backend/app/routers,
// backend/app/services).

export type EventType = "structured" | "informal";
export type Tone = "professional" | "casual";
export type QuestionKind = "text" | "single_choice" | "multi_choice" | "number";
export type RequestTargetType = "user" | "group";
export type RequestStatus =
  | "pending"
  | "accepted"
  | "declined"
  | "cancelled"
  | "expired";
export type ContactKind =
  | "discord"
  | "phone"
  | "email"
  | "instagram"
  | "facebook"
  | "linkedin"
  | "github"
  | "other";

export type Contact = { kind: ContactKind; value: string };

/** Every non-2xx response body: `{"error": {"code", "message"}}`. */
export type ApiErrorBody = { error: { code: string; message: string } };

// --- 1. Auth -------------------------------------------------------------------------------------

export type Me = {
  user_id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  orgs: { org_id: string; name: string }[];
  contacts: Contact[];
};

/** GET /api/me/profile. `summary`/`traits` are null until an interview summary is saved. */
export type Profile = {
  user_id: string;
  name: string;
  email: string;
  summary: string | null;
  /** Any JSON object; the agents currently send `{"highlights": [...]}`. */
  traits: Record<string, unknown> | null;
  socials: Contact[];
  contacts: Contact[];
  interviewed: boolean;
};

// --- 2. Orgs and feed ----------------------------------------------------------------------------

export type Verification = "manual" | "email_domain" | "roster";
export type OrgRole = "admin" | "member";
export type OrgStatus = "pending" | "approved" | "declined";

/** An item of GET /api/orgs, and the GET /api/orgs/{id} body. */
export type Org = {
  org_id: string;
  name: string;
  verification: Verification;
  email_domains: string[];
  discoverable: boolean;
  member_count: number;
  my_role: OrgRole | null;
  my_status: OrgStatus | null;
};

export type CreateOrgBody = {
  name: string;
  verification: Verification;
  email_domains: string[];
  discoverable: boolean;
};

export type JoinOrgResult = { status: "approved" | "pending" };

export type JoinRequest = {
  user_id: string;
  name: string;
  email: string;
  message: string | null;
  requested_at: string;
  roster_match: "email" | "name" | null;
};

export type JoinDecision = { user_id: string; status: "approved" | "declined" };

export type OrgFeedEvent = {
  event_id: string;
  name: string;
  type: EventType;
  tone: Tone;
  starts_at: string | null;
  member_count: number;
  joined: boolean;
};

export type OrgFeed = {
  org_id: string;
  name: string;
  events: OrgFeedEvent[];
};

// --- 3. Events -----------------------------------------------------------------------------------

export type Question = {
  question_id: string;
  text: string;
  kind: QuestionKind;
  options: string[] | null;
  required: boolean;
};

export type QuestionIn = {
  text: string;
  kind: QuestionKind;
  options: string[] | null;
  required: boolean;
};

export type CreateEventBody = {
  org_id?: string;
  name: string;
  description: string;
  type: EventType;
  tone: Tone;
  group_count?: number;
  min_size?: number;
  max_size?: number;
  max_groups_per_user?: number;
  required_fields: string[];
  questions: QuestionIn[];
  interview_enabled: boolean;
  starts_at?: string;
};

export type CreateEventResult = { event_id: string; share_url: string };

export type EventDetail = {
  event_id: string;
  org_id: string | null;
  name: string;
  description: string;
  type: EventType;
  tone: Tone;
  group_count: number | null;
  min_size: number | null;
  max_size: number | null;
  max_groups_per_user: number | null;
  required_fields: string[];
  questions: Question[];
  interview_enabled: boolean;
  starts_at: string | null;
  created_at: string;
  share_url: string;
  host: { user_id: string; name: string };
  my_membership: { joined_at: string; group_id: string | null } | null;
  stats: { member_count: number; groups_formed: number };
};

export type AnswerValue = string | number | string[];
export type FieldValue = string | number | boolean | string[];

export type JoinEventBody = {
  answers: { question_id: string; value: AnswerValue }[];
  fields: Record<string, FieldValue>;
  socials: Contact[];
};

export type JoinEventResult = {
  event_id: string;
  profile_status: "ready";
  interview: { available: boolean };
};

export type InterviewStart = {
  ws_url: string;
  interview_token: string;
  expires_in: number;
};

// --- 4. Recommendations --------------------------------------------------------------------------

export type PersonRecommendation = {
  user_id: string;
  name: string;
  summary: string | null;
  score: number;
  reason: string | null;
};

export type GroupRecommendation = {
  group_id: string;
  name: string;
  size: number;
  max_size: number;
  members: { user_id: string; name: string }[];
  score: number;
  reason: string | null;
};

export type RecommendationsResponse = {
  ranked_by: "gemini" | "similarity";
  people: PersonRecommendation[];
  groups: GroupRecommendation[];
};

// --- 5. Requests ---------------------------------------------------------------------------------

export type RequestBox = "incoming" | "outgoing";

export type CreateRequestBody = {
  event_id: string;
  target_type: RequestTargetType;
  target_id: string;
  message?: string;
};

export type CreateRequestResult = {
  request_id: string;
  status: RequestStatus;
  thread_id: string;
};

/** An item of GET /api/requests (backend services/requests.py list_requests). */
export type RequestItem = {
  request_id: string;
  event_id: string;
  /** Echoes the `box` query param. */
  direction: RequestBox;
  sender: { user_id: string; name: string | null };
  target_type: RequestTargetType;
  target: { user_id?: string; group_id?: string; name: string | null };
  /** The other side from the viewer: the target for outgoing, the sender for incoming. */
  other_party: { type: RequestTargetType; id: string; name: string | null };
  message: string | null;
  status: RequestStatus;
  thread_id: string | null;
  group_id: string | null;
  connection_id: string | null;
  created_at: string;
  decided_at: string | null;
};

export type RequestDecision = {
  request_id: string;
  status: RequestStatus;
  group_id: string | null;
  connection_id: string | null;
};

// --- 6. Threads ----------------------------------------------------------------------------------

export type ThreadKind = "request" | "group" | "connection";

/** GET /api/threads/{id}. `title` is viewer-relative. */
export type ThreadInfo = {
  thread_id: string;
  kind: ThreadKind;
  title: string | null;
  event_id: string;
  group_id: string | null;
  request_id: string | null;
  participants: { user_id: string; name: string }[];
};

export type Message = {
  message_id: string;
  sender_id: string;
  sender_name: string | null;
  text: string;
  sent_at: string;
};

// --- 7. Groups and connections -------------------------------------------------------------------

export type GroupMember = {
  user_id: string;
  name: string | null;
  summary: string | null;
  contacts: Contact[];
};

export type GroupPage = {
  group_id: string;
  event_id: string;
  name: string;
  thread_id: string | null;
  members: GroupMember[];
};

export type Connection = {
  connection_id: string;
  user_id: string;
  name: string | null;
  summary: string | null;
  contacts: Contact[];
  thread_id: string | null;
  connected_at: string;
};

// --- 9. Interview WebSocket ----------------------------------------------------------------------

export type InterviewClientMessage =
  | { type: "audio"; data: string }
  | { type: "text"; text: string }
  | { type: "end" };

export type InterviewServerMessage =
  | { type: "ready"; greeting_text: string }
  | { type: "audio"; data: string }
  | { type: "transcript"; role: "interviewer" | "user"; text: string; final: boolean }
  | { type: "turn_complete" }
  | { type: "interrupted" }
  | { type: "interview_complete"; summary_saved: boolean; summary: string | null }
  | { type: "error"; code: string; message: string };

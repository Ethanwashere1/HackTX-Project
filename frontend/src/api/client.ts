import { ApiError } from "./errors";
import { mockApi } from "./mocks";
import type {
  Connection,
  Contact,
  CreateEventBody,
  CreateEventResult,
  CreateOrgBody,
  CreateRequestBody,
  CreateRequestResult,
  EnrichmentContext,
  EnrichmentQuery,
  EventDetail,
  GroupPage,
  InterviewStart,
  JoinDecision,
  JoinEventBody,
  JoinEventResult,
  JoinOrgResult,
  JoinRequest,
  Me,
  Message,
  Org,
  OrgFeed,
  Profile,
  QuestionSuggestionsBody,
  QuestionSuggestionsResult,
  RecommendationsResponse,
  RequestBox,
  RequestDecision,
  RequestItem,
  ThreadInfo,
} from "./types";

/** Mocks are opt-in: only `VITE_USE_MOCKS=1` uses them. */
const useMocks = import.meta.env.VITE_USE_MOCKS === "1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw await ApiError.fromResponse(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const q = encodeURIComponent;

/** A WebSocket, or the mock stand-in, as the Interview page uses it. */
export type InterviewSocket = {
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  readonly readyState: number;
  send(data: string): void;
  close(): void;
};

/** `ws_url` may be absolute (`ws://localhost:8000/ws/interview`) or a path (`/agents/ws/interview`). */
export function interviewSocketUrl(wsUrl: string, token: string, input: "voice" | "text"): string {
  const url = new URL(wsUrl, window.location.href);
  if (url.protocol === "http:") url.protocol = "ws:";
  if (url.protocol === "https:") url.protocol = "wss:";
  url.searchParams.set("token", token);
  url.searchParams.set("input", input);
  return url.toString();
}

export type SeedUser = { email: string; name: string };

export const realApi = {
  useMocks: () => false,

  // --- auth / me ---
  async me(): Promise<Me | null> {
    try {
      return await request<Me>("/api/me");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },

  googleLoginUrl(next = "/"): string {
    return `/api/auth/google/login?next=${q(next)}`;
  },

  devLogin(user: SeedUser): Promise<Me> {
    return post<Me>("/api/auth/dev-login", user);
  },

  async logout(): Promise<void> {
    await post<void>("/api/auth/logout");
  },

  getProfile(): Promise<Profile> {
    return request<Profile>("/api/me/profile");
  },

  async saveContacts(contacts: Contact[]): Promise<Contact[]> {
    const res = await request<{ contacts: Contact[] }>("/api/me/contacts", {
      method: "PUT",
      body: JSON.stringify({ contacts }),
    });
    return res.contacts;
  },

  // --- orgs ---
  async listOrgs(): Promise<Org[]> {
    return (await request<{ orgs: Org[] }>("/api/orgs")).orgs;
  },

  /** 404 for an unknown org, or a hidden one the user has no membership row in. */
  getOrg(orgId: string): Promise<Org> {
    return request<Org>(`/api/orgs/${q(orgId)}`);
  },

  createOrg(body: CreateOrgBody): Promise<{ org_id: string; verification: string }> {
    return post("/api/orgs", body);
  },

  joinOrg(orgId: string, message?: string): Promise<JoinOrgResult> {
    return post(`/api/orgs/${q(orgId)}/join`, message ? { message } : {});
  },

  orgFeed(orgId: string): Promise<OrgFeed> {
    return request<OrgFeed>(`/api/orgs/${q(orgId)}/feed`);
  },

  async joinRequests(orgId: string): Promise<JoinRequest[]> {
    const res = await request<{ requests: JoinRequest[] }>(
      `/api/orgs/${q(orgId)}/join-requests?status=pending`,
    );
    return res.requests;
  },

  decideJoinRequest(
    orgId: string,
    userId: string,
    action: "approve" | "decline",
  ): Promise<JoinDecision> {
    return post(`/api/orgs/${q(orgId)}/join-requests/${q(userId)}/${action}`);
  },

  // --- events ---
  getEvent(eventId: string): Promise<EventDetail> {
    return request<EventDetail>(`/api/events/${q(eventId)}`);
  },

  createEvent(body: CreateEventBody): Promise<CreateEventResult> {
    return post("/api/events", body);
  },

  /** AI-drafted questionnaire questions for the Create event form. */
  suggestQuestions(body: QuestionSuggestionsBody): Promise<QuestionSuggestionsResult> {
    return post("/api/question-suggestions", body);
  },

  joinEvent(eventId: string, body: JoinEventBody): Promise<JoinEventResult> {
    return post(`/api/events/${q(eventId)}/join`, body);
  },

  startInterview(eventId: string): Promise<InterviewStart> {
    return post(`/api/events/${q(eventId)}/interview`);
  },

  openInterviewSocket(start: InterviewStart, input: "voice" | "text"): InterviewSocket {
    return new WebSocket(interviewSocketUrl(start.ws_url, start.interview_token, input));
  },

  recommendations(eventId: string, limit = 10): Promise<RecommendationsResponse> {
    return request(`/api/events/${q(eventId)}/recommendations?limit=${limit}`);
  },

  async connections(eventId: string): Promise<Connection[]> {
    return (await request<{ connections: Connection[] }>(`/api/events/${q(eventId)}/connections`))
      .connections;
  },

  // --- requests ---
  createRequest(body: CreateRequestBody): Promise<CreateRequestResult> {
    return post("/api/requests", body);
  },

  async listRequests(box: RequestBox, eventId?: string): Promise<RequestItem[]> {
    const params = new URLSearchParams({ box });
    if (eventId) params.set("event_id", eventId);
    return (await request<{ requests: RequestItem[] }>(`/api/requests?${params}`)).requests;
  },

  respondRequest(
    requestId: string,
    action: "accept" | "decline" | "cancel",
  ): Promise<RequestDecision> {
    return post(`/api/requests/${q(requestId)}/${action}`);
  },

  // --- threads ---
  getThread(threadId: string): Promise<ThreadInfo> {
    return request<ThreadInfo>(`/api/threads/${q(threadId)}`);
  },

  async listMessages(threadId: string, after?: string): Promise<Message[]> {
    const qs = after ? `?after=${q(after)}` : "";
    return (await request<{ messages: Message[] }>(`/api/threads/${q(threadId)}/messages${qs}`))
      .messages;
  },

  sendMessage(threadId: string, text: string): Promise<Message> {
    return post(`/api/threads/${q(threadId)}/messages`, { text });
  },

  async callUrl(threadId: string): Promise<string> {
    return (await post<{ call_url: string }>(`/api/threads/${q(threadId)}/call`)).call_url;
  },

  // --- groups ---
  getGroup(groupId: string): Promise<GroupPage> {
    return request<GroupPage>(`/api/groups/${q(groupId)}`);
  },

  // --- enrichment ---
  /** SerpAPI-backed Maps, Events (calendar) and social lookup near the browser's location. */
  enrichmentContext(opts: EnrichmentQuery = {}): Promise<EnrichmentContext> {
    const params = new URLSearchParams();
    if (opts.lat != null) params.set("lat", String(opts.lat));
    if (opts.lng != null) params.set("lng", String(opts.lng));
    if (opts.maps_q) params.set("maps_q", opts.maps_q);
    if (opts.calendar_q) params.set("calendar_q", opts.calendar_q);
    if (opts.social_kind) params.set("social_kind", opts.social_kind);
    if (opts.social_handle) params.set("social_handle", opts.social_handle);
    const qs = params.toString();
    return request<EnrichmentContext>(`/api/enrichment/context${qs ? `?${qs}` : ""}`);
  },
};

export type Api = typeof realApi;

export const api: Api = useMocks ? mockApi : realApi;

/** Seed users from `backend/app/seed.py`, for the dev-only login picker. */
export const SEED_USERS: SeedUser[] = [
  { email: "priya@seed.squadup.dev", name: "Priya Sharma" },
  { email: "ana@seed.squadup.dev", name: "Ana Ruiz" },
  { email: "morgan@seed.squadup.dev", name: "Morgan Reyes" },
];

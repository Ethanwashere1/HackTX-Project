import {
  DEMO_DATA_ENABLED,
  demoEnrichment,
  mockConnections,
  mockEvents,
  mockGroup,
  mockMe,
  mockOrgFeed,
  mockProfile,
  mockRecommendations,
  mockRequests,
  mockThread,
  type EnrichmentContext,
} from "../demo";
import type {
  EventDetail,
  GroupPage,
  Me,
  OrgFeed,
  Profile,
  RecommendationsResponse,
  RequestItem,
  Thread,
} from "./types";

/** When false, all reads hit the real backend/DB — delete `src/demo/` for deploy. */
const useMocks = DEMO_DATA_ENABLED;

type ApiError = { error: { code: string; message: string } };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let body: ApiError | null = null;
    try {
      body = (await res.json()) as ApiError;
    } catch {
      /* ignore */
    }
    throw new Error(body?.error?.message ?? `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

let sessionAuthed = useMocks;

export const api = {
  useMocks: () => useMocks,

  async me(): Promise<Me | null> {
    if (useMocks) return sessionAuthed ? mockMe : null;
    try {
      return await request<Me>("/api/me");
    } catch {
      return null;
    }
  },

  googleLoginUrl(next = "/orgs/org_ut"): string {
    if (useMocks) return `/login?dev=1&next=${encodeURIComponent(next)}`;
    return `/api/auth/google/login?next=${encodeURIComponent(next)}`;
  },

  async devLogin(): Promise<Me> {
    if (useMocks) {
      sessionAuthed = true;
      return mockMe;
    }
    return request<Me>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ email: mockMe.email, name: mockMe.name }),
    });
  },

  async logout(): Promise<void> {
    if (useMocks) {
      sessionAuthed = false;
      return;
    }
    await request<void>("/api/auth/logout", { method: "POST" });
  },

  async orgFeed(orgId: string): Promise<OrgFeed> {
    if (useMocks) return { ...mockOrgFeed, org_id: orgId };
    return request<OrgFeed>(`/api/orgs/${orgId}/feed`);
  },

  async getEvent(eventId: string): Promise<EventDetail> {
    if (useMocks) {
      const evt = mockEvents[eventId] ?? mockEvents.evt_hacktx;
      return structuredClone(evt);
    }
    return request<EventDetail>(`/api/events/${eventId}`);
  },

  async createEvent(body: Record<string, unknown>): Promise<{ event_id: string }> {
    if (useMocks) {
      const eventId = `evt_${Date.now().toString(36)}`;
      const questions = Array.isArray(body.questions)
        ? (body.questions as { text: string; kind: string; options: string[] | null; required: boolean }[]).map(
            (q, i) => ({
              question_id: `q_${i + 1}`,
              text: q.text,
              kind: q.kind as EventDetail["questions"][number]["kind"],
              options: q.options,
              required: Boolean(q.required),
            }),
          )
        : [];
      mockEvents[eventId] = {
        event_id: eventId,
        org_id: (body.org_id as string) ?? "org_ut",
        name: String(body.name ?? "New event"),
        description: String(body.description ?? ""),
        type: (body.type as EventDetail["type"]) ?? "structured",
        tone: (body.tone as EventDetail["tone"]) ?? "casual",
        group_count: (body.group_count as number | null) ?? null,
        min_size: (body.min_size as number | null) ?? null,
        max_size: (body.max_size as number | null) ?? null,
        max_groups_per_user: 1,
        required_fields: (body.required_fields as string[]) ?? [],
        questions,
        interview_enabled: Boolean(body.interview_enabled),
        starts_at: null,
        created_at: new Date().toISOString(),
        share_url: `https://squadup.tech/events/${eventId}`,
        host: { user_id: mockMe.user_id, name: mockMe.name },
        my_membership: null,
        stats: { member_count: 1, groups_formed: 0 },
      };
      return { event_id: eventId };
    }
    return request("/api/events", { method: "POST", body: JSON.stringify(body) });
  },

  async joinEvent(
    eventId: string,
    body: Record<string, unknown>,
  ): Promise<{ event_id: string; profile_status: string; interview: { available: boolean } }> {
    if (useMocks) {
      const evt = mockEvents[eventId] ?? mockEvents.evt_hacktx;
      if (evt.host.user_id === mockMe.user_id) {
        throw new Error(
          "You're the host of this event — hosts manage the event and can't join as a participant",
        );
      }
      evt.my_membership = { joined_at: new Date().toISOString(), group_id: null };
      return {
        event_id: eventId,
        profile_status: "ready",
        interview: { available: evt.interview_enabled },
      };
    }
    return request(`/api/events/${eventId}/join`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async recommendations(eventId: string): Promise<RecommendationsResponse> {
    if (useMocks) {
      if (eventId === "evt_study") {
        return {
          ranked_by: "agent",
          results: mockConnections.map((c) => ({
            candidate_type: "user" as const,
            id: c.user_id,
            name: c.name,
            score: 0.8,
            reason: c.reason,
            tags: c.tags,
          })),
        };
      }
      return mockRecommendations;
    }
    return request(`/api/events/${eventId}/recommendations`);
  },

  async createRequest(body: {
    target_type: "user" | "group";
    target_id: string;
    event_id: string;
  }): Promise<{ request_id: string; thread_id: string }> {
    if (useMocks) {
      if (body.target_type === "group") {
        const group = body.target_id === mockGroup.group_id ? mockGroup : null;
        if (group?.members.some((m) => m.user_id === mockMe.user_id)) {
          throw new Error("You're already in this squad — owners and members can't join again");
        }
        if (group?.owner_user_id === mockMe.user_id) {
          throw new Error("You're the owner of this squad and can't join it again");
        }
      }
      return { request_id: "req_2", thread_id: "thr_1" };
    }
    return request("/api/requests", { method: "POST", body: JSON.stringify(body) });
  },

  async listRequests(): Promise<RequestItem[]> {
    if (useMocks) return mockRequests;
    const res = await request<{ requests: RequestItem[] }>("/api/requests");
    return res.requests;
  },

  async respondRequest(
    requestId: string,
    action: "accept" | "decline",
  ): Promise<{ group_id?: string }> {
    if (useMocks) return action === "accept" ? { group_id: "grp_pixel" } : {};
    return request(`/api/requests/${requestId}/${action}`, { method: "POST" });
  },

  async getThread(threadId: string): Promise<Thread> {
    if (useMocks) return { ...mockThread, thread_id: threadId };
    return request(`/api/threads/${threadId}`);
  },

  async sendMessage(threadId: string, text: string): Promise<void> {
    if (useMocks) {
      mockThread.messages.push({
        message_id: `msg_${mockThread.messages.length + 1}`,
        sender_id: mockMe.user_id,
        sender_name: mockMe.name,
        text,
        created_at: new Date().toISOString(),
      });
      return;
    }
    await request(`/api/threads/${threadId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  async getGroup(groupId: string): Promise<GroupPage> {
    if (useMocks) return { ...mockGroup, group_id: groupId };
    return request(`/api/groups/${groupId}`);
  },

  async getProfile(): Promise<Profile> {
    if (useMocks) return mockProfile;
    return request("/api/me/profile");
  },

  async saveContacts(contacts: Me["contacts"]): Promise<Me["contacts"]> {
    if (useMocks) {
      mockMe.contacts = contacts;
      mockProfile.contacts = contacts;
      return contacts;
    }
    const res = await request<{ contacts: Me["contacts"] }>("/api/me/contacts", {
      method: "PUT",
      body: JSON.stringify({ contacts }),
    });
    return res.contacts;
  },

  /**
   * SerpAPI-backed context: Google Maps, Google Events (calendar), social search,
   * and the browser's current location (passed as lat/lng).
   */
  async enrichmentContext(opts?: {
    lat?: number | null;
    lng?: number | null;
    maps_q?: string;
    calendar_q?: string;
    social_kind?: string;
    social_handle?: string;
  }): Promise<EnrichmentContext> {
    if (useMocks) {
      return {
        ...demoEnrichment,
        location: {
          ...demoEnrichment.location,
          lat: opts?.lat ?? null,
          lng: opts?.lng ?? null,
          label:
            opts?.lat != null && opts?.lng != null
              ? "Browser geolocation"
              : demoEnrichment.location.label,
        },
      };
    }
    const params = new URLSearchParams();
    if (opts?.lat != null) params.set("lat", String(opts.lat));
    if (opts?.lng != null) params.set("lng", String(opts.lng));
    if (opts?.maps_q) params.set("maps_q", opts.maps_q);
    if (opts?.calendar_q) params.set("calendar_q", opts.calendar_q);
    if (opts?.social_kind) params.set("social_kind", opts.social_kind);
    if (opts?.social_handle) params.set("social_handle", opts.social_handle);
    const qs = params.toString();
    return request<EnrichmentContext>(`/api/enrichment/context${qs ? `?${qs}` : ""}`);
  },
};

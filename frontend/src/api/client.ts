import {
  mockConnections,
  mockEvents,
  mockGroup,
  mockMe,
  mockOrgFeed,
  mockProfile,
  mockRecommendations,
  mockRequests,
  mockThread,
} from "./mocks";
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

const useMocks =
  import.meta.env.VITE_USE_MOCKS === "1" ||
  import.meta.env.VITE_USE_MOCKS === undefined ||
  import.meta.env.VITE_USE_MOCKS === "";

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
      return { event_id: "evt_hacktx" };
    }
    return request("/api/events", { method: "POST", body: JSON.stringify(body) });
  },

  async joinEvent(
    eventId: string,
    body: Record<string, unknown>,
  ): Promise<{ event_id: string; profile_status: string; interview: { available: boolean } }> {
    if (useMocks) {
      const evt = mockEvents[eventId];
      if (evt) evt.my_membership = { joined_at: new Date().toISOString(), group_id: null };
      return {
        event_id: eventId,
        profile_status: "ready",
        interview: { available: evt?.interview_enabled ?? false },
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
    if (useMocks) return { request_id: "req_2", thread_id: "thr_1" };
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
};

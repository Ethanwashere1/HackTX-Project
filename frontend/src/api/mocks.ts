// Mock mode (VITE_USE_MOCKS=1): an in-memory stand-in for the backend with the real response
// shapes, so every page renders without a server. State lives for the page load.
import type { Api, InterviewSocket, SeedUser } from "./client";
import { ApiError } from "./errors";
import type {
  Connection,
  EnrichmentContext,
  EventDetail,
  GroupPage,
  InterviewServerMessage,
  JoinRequest,
  Me,
  Message,
  Org,
  OrgFeedEvent,
  Profile,
  QuestionIn,
  RecommendationsResponse,
  RequestItem,
  ThreadInfo,
} from "./types";

const now = () => new Date().toISOString();
const clone = <T>(v: T): T => structuredClone(v);
const delay = <T>(v: T, ms = 120) => new Promise<T>((r) => window.setTimeout(() => r(v), ms));

export const mockMe: Me = {
  user_id: "usr_maya",
  name: "Maya Chen",
  email: "maya@utexas.edu",
  avatar_url: null,
  orgs: [{ org_id: "org_ut", name: "UT Austin" }],
  contacts: [
    { kind: "discord", value: "maya#2048" },
    { kind: "phone", value: "+1 512-555-0199" },
  ],
};

let signedIn = false;

const mockOrgs: Org[] = [
  {
    org_id: "org_ut",
    name: "UT Austin",
    verification: "email_domain",
    email_domains: ["utexas.edu"],
    discoverable: true,
    member_count: 312,
    my_role: "admin",
    my_status: "approved",
  },
  {
    org_id: "org_acc",
    name: "Austin Creative Collective",
    verification: "manual",
    email_domains: [],
    discoverable: true,
    member_count: 48,
    my_role: null,
    my_status: null,
  },
];

const mockJoinRequests: Record<string, JoinRequest[]> = {
  org_ut: [
    {
      user_id: "usr_ben",
      name: "Ben Li",
      email: "ben@gmail.com",
      message: "CS junior, here for HackTX",
      requested_at: "2026-10-24T22:10:00Z",
      roster_match: "name",
    },
    {
      user_id: "usr_kai",
      name: "Kai Nguyen",
      email: "kai@outlook.com",
      message: null,
      requested_at: "2026-10-24T23:40:00Z",
      roster_match: null,
    },
  ],
};

const baseEvent = {
  org_id: "org_ut",
  created_at: "2026-10-24T20:00:00Z",
  host: { user_id: "usr_morgan", name: "Morgan Reyes" },
  my_membership: null,
};

export const mockEvents: Record<string, EventDetail> = {
  evt_hacktx: {
    ...baseEvent,
    event_id: "evt_hacktx",
    name: "HackTX squad-up",
    description: "Find your hackathon squad. Mutual consent before anything forms.",
    type: "structured",
    tone: "casual",
    group_count: 6,
    min_size: 3,
    max_size: 4,
    max_groups_per_user: 1,
    required_fields: ["skills", "experience_level"],
    questions: [
      {
        question_id: "q_1",
        text: "What role do you want?",
        kind: "single_choice",
        options: ["frontend", "backend", "design", "ml"],
        required: true,
      },
      { question_id: "q_2", text: "What do you want to build?", kind: "text", options: null, required: false },
      {
        question_id: "q_3",
        text: "Which tracks interest you?",
        kind: "multi_choice",
        options: ["Education", "Social good", "Sustainability", "Health"],
        required: false,
      },
    ],
    interview_enabled: true,
    starts_at: "2026-10-25T15:00:00Z",
    share_url: "http://localhost:5173/events/evt_hacktx",
    stats: { member_count: 42, groups_formed: 3 },
  },
  evt_study: {
    ...baseEvent,
    event_id: "evt_study",
    name: "Study buddies",
    description: "1:1 connections for studying, no squads.",
    type: "informal",
    tone: "casual",
    group_count: null,
    min_size: null,
    max_size: null,
    max_groups_per_user: null,
    required_fields: ["major"],
    questions: [
      { question_id: "q_s1", text: "Which courses are you taking?", kind: "text", options: null, required: true },
      { question_id: "q_s2", text: "Hours per week you can study together", kind: "number", options: null, required: false },
    ],
    interview_enabled: false,
    starts_at: "2026-10-26T18:00:00Z",
    share_url: "http://localhost:5173/events/evt_study",
    stats: { member_count: 18, groups_formed: 0 },
  },
};

function feedItem(e: EventDetail): OrgFeedEvent {
  return {
    event_id: e.event_id,
    name: e.name,
    type: e.type,
    tone: e.tone,
    starts_at: e.starts_at,
    member_count: e.stats.member_count,
    joined: e.my_membership !== null,
  };
}

const people: RecommendationsResponse["people"] = [
  {
    user_id: "usr_ben",
    name: "Ben Li",
    summary: "Backend engineer focused on APIs and databases.",
    score: 0.86,
    reason: "Backend and ML overlap; both want an ambitious but friendly weekend pace.",
  },
  {
    user_id: "usr_priya",
    name: "Priya Sharma",
    summary: "ML / NLP builder who wants to ship an LLM demo.",
    score: 0.79,
    reason: null,
  },
];

const groups: RecommendationsResponse["groups"] = [
  {
    group_id: "grp_neural",
    name: "Squad Neural",
    size: 2,
    max_size: 4,
    members: [
      { user_id: "usr_dev", name: "Dev Patel" },
      { user_id: "usr_eli", name: "Eli Park" },
    ],
    score: 0.91,
    reason: "They're missing a frontend person and you listed React.",
  },
];

const mockConnections: Connection[] = [
  {
    connection_id: "con_1",
    user_id: "usr_hiro",
    name: "Hiro Tanaka",
    summary: "Grinding CS 439 this week, prefers quiet library sessions.",
    contacts: [{ kind: "discord", value: "hiro#7781" }],
    thread_id: "thr_1",
    connected_at: "2026-10-24T22:00:00Z",
  },
];

const mockGroups: Record<string, GroupPage> = {
  grp_pixel: {
    group_id: "grp_pixel",
    event_id: "evt_hacktx",
    name: "Squad Pixel",
    thread_id: "thr_g1",
    members: [
      {
        user_id: "usr_ben",
        name: "Ben Li",
        summary: "Backend engineer focused on APIs and databases.",
        contacts: [
          { kind: "discord", value: "benli#4411" },
          { kind: "phone", value: "+1 512-555-0102" },
        ],
      },
      {
        user_id: "usr_cara",
        name: "Cara Okafor",
        summary: "Product designer, Figma and user research.",
        contacts: [{ kind: "github", value: "cara-designs" }],
      },
    ],
  },
};

let mockRequests: RequestItem[] = [
  {
    request_id: "req_1",
    event_id: "evt_hacktx",
    direction: "incoming",
    sender: { user_id: "usr_ben", name: "Ben Li" },
    target_type: "user",
    target: { user_id: "usr_maya", name: "Maya Chen" },
    other_party: { type: "user", id: "usr_ben", name: "Ben Li" },
    message: "Want to squad up? I can cover the backend.",
    status: "pending",
    thread_id: "thr_1",
    group_id: null,
    connection_id: null,
    created_at: "2026-10-25T01:10:00Z",
    decided_at: null,
  },
  {
    request_id: "req_2",
    event_id: "evt_hacktx",
    direction: "outgoing",
    sender: { user_id: "usr_maya", name: "Maya Chen" },
    target_type: "group",
    target: { group_id: "grp_neural", name: "Squad Neural" },
    other_party: { type: "group", id: "grp_neural", name: "Squad Neural" },
    message: "I'd love to do the frontend for you.",
    status: "pending",
    thread_id: "thr_2",
    group_id: null,
    connection_id: null,
    created_at: "2026-10-25T01:05:00Z",
    decided_at: null,
  },
];

const mockThreads: Record<string, ThreadInfo> = {
  thr_1: {
    thread_id: "thr_1",
    kind: "request",
    title: "Ben Li",
    event_id: "evt_hacktx",
    group_id: null,
    request_id: "req_1",
    participants: [
      { user_id: "usr_ben", name: "Ben Li" },
      { user_id: "usr_maya", name: "Maya Chen" },
    ],
  },
  thr_2: {
    thread_id: "thr_2",
    kind: "request",
    title: "Squad Neural",
    event_id: "evt_hacktx",
    group_id: "grp_neural",
    request_id: "req_2",
    participants: [
      { user_id: "usr_maya", name: "Maya Chen" },
      { user_id: "usr_dev", name: "Dev Patel" },
      { user_id: "usr_eli", name: "Eli Park" },
    ],
  },
  thr_g1: {
    thread_id: "thr_g1",
    kind: "group",
    title: "Squad Pixel",
    event_id: "evt_hacktx",
    group_id: "grp_pixel",
    request_id: null,
    participants: [
      { user_id: "usr_ben", name: "Ben Li" },
      { user_id: "usr_cara", name: "Cara Okafor" },
      { user_id: "usr_maya", name: "Maya Chen" },
    ],
  },
};

const mockMessages: Record<string, Message[]> = {
  thr_1: [
    {
      message_id: "msg_001",
      sender_id: "usr_ben",
      sender_name: "Ben Li",
      text: "Hey! I saw you're doing frontend. I've got an API idea for bus arrivals.",
      sent_at: "2026-10-25T01:06:00Z",
    },
  ],
  thr_2: [],
  thr_g1: [
    {
      message_id: "msg_002",
      sender_id: "usr_cara",
      sender_name: "Cara Okafor",
      text: "Sketching the onboarding flow in Figma now.",
      sent_at: "2026-10-25T02:00:00Z",
    },
  ],
};
let messageSeq = 100;

const mockProfile = (): Profile => ({
  user_id: mockMe.user_id,
  name: mockMe.name,
  email: mockMe.email,
  overview:
    "Maya is a frontend-leaning builder at UT Austin who gravitates to climate and campus-tools " +
    "ideas. She pairs well with backend or ML folks and wants an ambitious but friendly weekend.",
  summary: "Frontend-focused builder who loves climate apps; wants a chill but ambitious squad.",
  traits: { highlights: ["pairing", "wants to win", "free all weekend"] },
  socials: [{ kind: "github", value: "mayachen" }],
  contacts: clone(mockMe.contacts),
  interviewed: true,
});

function notFound(what: string): never {
  throw new ApiError(404, "not_found", `${what} not found`);
}

function eventOr404(eventId: string): EventDetail {
  return mockEvents[eventId] ?? notFound("Event");
}

/** Plays the interview protocol (contract section 9) locally. */
class MockInterviewSocket implements InterviewSocket {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  readyState = 0;
  private heardAudio = false;
  private timers: number[] = [];

  constructor() {
    this.later(50, () => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
      this.emit({
        type: "ready",
        greeting_text: `Hey ${mockMe.name.split(" ")[0]}! What are you hoping to build or find here?`,
      });
    });
  }

  private later(ms: number, fn: () => void) {
    this.timers.push(window.setTimeout(fn, ms));
  }

  private emit(msg: InterviewServerMessage) {
    if (this.readyState !== 1) return;
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(msg) }));
  }

  private reply(text: string) {
    this.later(700, () => {
      this.emit({ type: "transcript", role: "interviewer", text, final: true });
      this.emit({ type: "turn_complete" });
    });
  }

  send(data: string) {
    const msg = JSON.parse(data) as { type: string; text?: string };
    if (msg.type === "text") {
      this.reply("Love that. Competitive or chill builder energy this weekend?");
    } else if (msg.type === "audio" && !this.heardAudio) {
      this.heardAudio = true;
      this.later(1200, () =>
        this.emit({
          type: "transcript",
          role: "user",
          text: "I'm mostly React and frontend. I want a climate or campus-tools angle.",
          final: true,
        }),
      );
      this.reply("Nice. What kind of squadmates help you do your best work?");
    } else if (msg.type === "end") {
      this.later(600, () => {
        this.emit({
          type: "interview_complete",
          summary_saved: true,
          summary: "Frontend builder into climate and campus tools; wants a chill but ambitious squad.",
        });
        this.close();
      });
    }
  }

  close() {
    if (this.readyState === 3) return;
    this.timers.forEach((t) => window.clearTimeout(t));
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
}

export const mockApi: Api = {
  useMocks: () => true,

  async me() {
    return delay(signedIn ? clone(mockMe) : null, 0);
  },
  googleLoginUrl(next = "/") {
    return `/login?next=${encodeURIComponent(next)}`;
  },
  async devLogin(user: SeedUser) {
    signedIn = true;
    mockMe.name = user.name;
    mockMe.email = user.email;
    return clone(mockMe);
  },
  async logout() {
    signedIn = false;
  },
  async getProfile() {
    return delay(mockProfile());
  },
  async saveContacts(contacts) {
    mockMe.contacts = clone(contacts);
    return delay(clone(contacts));
  },

  async listOrgs() {
    return delay(clone(mockOrgs));
  },
  async getOrg(orgId) {
    return delay(clone(mockOrgs.find((o) => o.org_id === orgId) ?? notFound("Organization")));
  },
  async createOrg(body) {
    const org_id = `org_${mockOrgs.length + 1}`;
    mockOrgs.push({
      org_id,
      name: body.name,
      verification: body.verification,
      email_domains: body.email_domains,
      discoverable: body.discoverable,
      member_count: 1,
      my_role: "admin",
      my_status: "approved",
    });
    mockMe.orgs.push({ org_id, name: body.name });
    return delay({ org_id, verification: body.verification });
  },
  async joinOrg(orgId) {
    const org = mockOrgs.find((o) => o.org_id === orgId) ?? notFound("Organization");
    if (org.my_status === "approved") throw new ApiError(409, "already_member", "Already a member");
    org.my_status = "pending";
    return delay({ status: "pending" as const });
  },
  async orgFeed(orgId) {
    const org = mockOrgs.find((o) => o.org_id === orgId);
    if (!org || org.my_status !== "approved") {
      throw new ApiError(403, "not_org_member", "Join this org to see its events");
    }
    const events = Object.values(mockEvents).filter((e) => e.org_id === orgId).map(feedItem);
    return delay({ org_id: orgId, name: org.name, events });
  },
  async joinRequests(orgId) {
    return delay(clone(mockJoinRequests[orgId] ?? []));
  },
  async decideJoinRequest(orgId, userId, action) {
    mockJoinRequests[orgId] = (mockJoinRequests[orgId] ?? []).filter((r) => r.user_id !== userId);
    return delay({ user_id: userId, status: action === "approve" ? ("approved" as const) : ("declined" as const) });
  },

  async getEvent(eventId) {
    return delay(clone(eventOr404(eventId)));
  },
  async createEvent(body) {
    const event_id = `evt_${Object.keys(mockEvents).length + 1}`;
    mockEvents[event_id] = {
      ...baseEvent,
      event_id,
      org_id: body.org_id ?? null,
      name: body.name,
      description: body.description,
      type: body.type,
      tone: body.tone,
      group_count: body.group_count ?? null,
      min_size: body.min_size ?? null,
      max_size: body.max_size ?? null,
      max_groups_per_user: body.type === "structured" ? (body.max_groups_per_user ?? 1) : null,
      required_fields: body.required_fields,
      questions: body.questions.map((qn, i) => ({ ...qn, question_id: `q_${event_id}_${i}` })),
      interview_enabled: body.interview_enabled,
      starts_at: body.starts_at ?? null,
      host: { user_id: mockMe.user_id, name: mockMe.name },
      share_url: `http://localhost:5173/events/${event_id}`,
      stats: { member_count: 0, groups_formed: 0 },
    };
    return delay({ event_id, share_url: mockEvents[event_id].share_url });
  },
  async suggestQuestions(body) {
    const existing = new Set((body.existing_questions ?? []).map((qn) => qn.text.toLowerCase()));
    const pool: QuestionIn[] = [
      {
        text: body.type === "structured" ? "What role would you take on a squad?" : "What do you want to get out of a 1:1?",
        kind: "single_choice",
        options:
          body.type === "structured"
            ? ["frontend", "backend", "design", "ml", "product"]
            : ["study partner", "mentor", "new friend", "project buddy"],
        required: true,
      },
      { text: "Describe a project you're proud of.", kind: "text", options: null, required: false },
      {
        text: "Which topics excite you most?",
        kind: "multi_choice",
        options: ["AI", "Climate", "Health", "Education", "Fintech"],
        required: false,
      },
      { text: "How many hours can you commit?", kind: "number", options: null, required: false },
      {
        text: body.tone === "professional" ? "What's your experience level?" : "What's your vibe this weekend?",
        kind: "single_choice",
        options:
          body.tone === "professional"
            ? ["beginner", "intermediate", "advanced"]
            : ["chill builder", "competitive", "explore & learn"],
        required: false,
      },
    ];
    const questions = pool
      .filter((qn) => !existing.has(qn.text.toLowerCase()))
      .slice(0, body.count ?? 3);
    return delay({ questions: clone(questions) }, 300);
  },
  async joinEvent(eventId) {
    const evt = eventOr404(eventId);
    if (evt.host.user_id === mockMe.user_id) {
      throw new ApiError(
        403,
        "is_host",
        "You're the host of this event — hosts manage the event and can't join as a participant",
      );
    }
    if (evt.my_membership) throw new ApiError(409, "already_joined", "You already joined this event");
    evt.my_membership = { joined_at: now(), group_id: null };
    evt.stats.member_count += 1;
    return delay({
      event_id: eventId,
      profile_status: "ready" as const,
      interview: { available: evt.interview_enabled },
    });
  },
  async startInterview(eventId) {
    const evt = eventOr404(eventId);
    if (!evt.my_membership) throw new ApiError(403, "forbidden", "Join the event first");
    if (!evt.interview_enabled) throw new ApiError(409, "interview_disabled", "No interview");
    return delay({ ws_url: "ws://mock/ws/interview", interview_token: "itk_mock", expires_in: 600 });
  },
  openInterviewSocket() {
    return new MockInterviewSocket();
  },
  async recommendations(eventId) {
    const evt = eventOr404(eventId);
    if (!evt.my_membership) throw new ApiError(403, "forbidden", "Join the event to see recommendations");
    if (evt.type === "informal") {
      return delay({ ranked_by: "similarity" as const, people: clone(people), groups: [] });
    }
    if (evt.my_membership.group_id) {
      return delay({ ranked_by: "similarity" as const, people: [], groups: [] });
    }
    const full = evt.group_count !== null && evt.stats.groups_formed >= evt.group_count;
    return delay({
      ranked_by: "gemini" as const,
      people: full ? [] : clone(people),
      groups: clone(groups),
    });
  },
  async connections(eventId) {
    const evt = eventOr404(eventId);
    return delay(evt.type === "informal" ? clone(mockConnections) : []);
  },

  async createRequest(body) {
    const evt = eventOr404(body.event_id);
    if (body.target_type === "group" && evt.my_membership?.group_id === body.target_id) {
      throw new ApiError(
        409,
        "already_in_group",
        "You're already in this squad — owners and members can't join again",
      );
    }
    const request_id = `req_${mockRequests.length + 10}`;
    const thread_id = `thr_${request_id}`;
    const targetName =
      body.target_type === "group"
        ? (groups.find((g) => g.group_id === body.target_id)?.name ?? "Group")
        : (people.find((p) => p.user_id === body.target_id)?.name ?? "Someone");
    mockRequests = [
      {
        request_id,
        event_id: evt.event_id,
        direction: "outgoing",
        sender: { user_id: mockMe.user_id, name: mockMe.name },
        target_type: body.target_type,
        target:
          body.target_type === "group"
            ? { group_id: body.target_id, name: targetName }
            : { user_id: body.target_id, name: targetName },
        other_party: { type: body.target_type, id: body.target_id, name: targetName },
        message: body.message ?? null,
        status: "pending",
        thread_id,
        group_id: null,
        connection_id: null,
        created_at: now(),
        decided_at: null,
      },
      ...mockRequests,
    ];
    mockThreads[thread_id] = {
      thread_id,
      kind: "request",
      title: targetName,
      event_id: evt.event_id,
      group_id: body.target_type === "group" ? body.target_id : null,
      request_id,
      participants: [{ user_id: mockMe.user_id, name: mockMe.name }],
    };
    mockMessages[thread_id] = [];
    return delay({ request_id, status: "pending" as const, thread_id });
  },
  async listRequests(box, eventId) {
    return delay(
      clone(mockRequests.filter((r) => r.direction === box && (!eventId || r.event_id === eventId))),
    );
  },
  async respondRequest(requestId, action) {
    const req = mockRequests.find((r) => r.request_id === requestId) ?? notFound("Request");
    if (req.status !== "pending") throw new ApiError(409, "request_not_pending", "Already handled");
    req.status = action === "accept" ? "accepted" : action === "decline" ? "declined" : "cancelled";
    req.decided_at = now();
    if (action === "accept") {
      req.group_id = "grp_pixel";
      const evt = mockEvents[req.event_id];
      if (evt?.my_membership) evt.my_membership.group_id = "grp_pixel";
    }
    return delay({
      request_id: req.request_id,
      status: req.status,
      group_id: req.group_id,
      connection_id: req.connection_id,
    });
  },

  async getThread(threadId) {
    return delay(clone(mockThreads[threadId] ?? notFound("Thread")));
  },
  async listMessages(threadId, after) {
    const all = mockMessages[threadId] ?? notFound("Thread");
    return delay(clone(after ? all.filter((m) => m.message_id > after) : all), 40);
  },
  async sendMessage(threadId, text) {
    const msg: Message = {
      message_id: `msg_${++messageSeq}`,
      sender_id: mockMe.user_id,
      sender_name: mockMe.name,
      text,
      sent_at: now(),
    };
    (mockMessages[threadId] ??= []).push(msg);
    return delay(clone(msg), 40);
  },
  async callUrl(threadId) {
    return delay(`https://meet.jit.si/squadup-${threadId.replace("_", "")}-mock`);
  },

  async getGroup(groupId) {
    const g = mockGroups[groupId] ?? notFound("Group");
    const withMe: GroupPage = clone(g);
    if (!withMe.members.some((m) => m.user_id === mockMe.user_id)) {
      withMe.members.push({
        user_id: mockMe.user_id,
        name: mockMe.name,
        summary: "React and product polish.",
        contacts: clone(mockMe.contacts),
      });
    }
    // The earliest member is the squad owner.
    withMe.owner_user_id = withMe.members[0]?.user_id ?? null;
    return delay(withMe);
  },

  async enrichmentContext(opts = {}) {
    const ctx = clone(demoEnrichment);
    if (opts.lat != null && opts.lng != null) {
      ctx.location = { ...ctx.location, lat: opts.lat, lng: opts.lng, label: "Browser geolocation" };
    }
    if (opts.social_kind || opts.social_handle) {
      const kind = opts.social_kind ?? ctx.social.result.kind;
      const handle = opts.social_handle ?? ctx.social.result.handle;
      ctx.social.result = {
        ...ctx.social.result,
        kind,
        handle,
        profile_url: `https://${kind}.com/${handle.replace(/^@/, "")}`,
      };
    }
    return delay(ctx);
  },
};

/** SerpAPI-shaped demo payload, matching the backend's `demo_fallback` when no key is set. */
const demoEnrichment: EnrichmentContext = {
  location: {
    lat: null,
    lng: null,
    label: "Default · UT Austin campus",
    fallback_lat: 30.2849,
    fallback_lng: -97.7341,
  },
  maps: {
    source: "demo_fallback",
    engine: "google_maps",
    results: [
      {
        title: "PCL (Perry-Castañeda Library)",
        address: "101 E 21st St, Austin, TX",
        rating: 4.6,
        type: "library",
        maps_url: "https://maps.google.com/?q=Perry-Castaneda+Library",
      },
      {
        title: "GDC (Gates Dell Complex)",
        address: "2317 Speedway, Austin, TX",
        rating: 4.7,
        type: "university",
        maps_url: "https://maps.google.com/?q=Gates+Dell+Complex",
      },
      {
        title: "Spider House Cafe",
        address: "2908 Fruth St, Austin, TX",
        rating: 4.5,
        type: "cafe",
        maps_url: "https://maps.google.com/?q=Spider+House+Cafe",
      },
    ],
  },
  calendar: {
    source: "demo_fallback",
    engine: "google_events",
    results: [
      {
        title: "HackTX Opening Ceremony",
        date: "Sat, Oct 25 · 10:00 AM",
        venue: "GDC Auditorium",
        link: "https://hacktx.com",
      },
      {
        title: "UTCS Career Fair",
        date: "Tue, Oct 28 · 1:00 PM",
        venue: "PCL",
        link: "https://www.cs.utexas.edu",
      },
      {
        title: "Campus photo walk meetup",
        date: "Sun, Oct 27 · 5:30 PM",
        venue: "Main Mall",
        link: "https://maps.google.com/?q=UT+Austin+Main+Mall",
      },
    ],
  },
  social: {
    source: "demo_fallback",
    engine: "google",
    result: {
      kind: "github",
      handle: "mayachen",
      display_name: "mayachen",
      bio: "Builder · UT Austin · open to HackTX squads",
      profile_url: "https://github.com/mayachen",
      notes: "Public profile signals: React, campus tools, climate apps.",
    },
  },
  serpapi_configured: false,
};

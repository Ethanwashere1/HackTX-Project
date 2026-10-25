import type {
  Connection,
  EventDetail,
  GroupPage,
  Me,
  OrgFeed,
  Profile,
  RecommendationsResponse,
  RequestItem,
  Thread,
} from "./types";

export const mockMe: Me = {
  user_id: "usr_maya",
  name: "Maya Chen",
  email: "maya@utexas.edu",
  avatar_url: null,
  orgs: [{ org_id: "org_ut", name: "UT Austin" }],
  contacts: [
    { kind: "discord", value: "maya#2048" },
    { kind: "github", value: "mayachen" },
  ],
};

export const mockOrgFeed: OrgFeed = {
  org_id: "org_ut",
  name: "UT Austin",
  events: [
    {
      event_id: "evt_hacktx",
      name: "HackTX team-up",
      type: "structured",
      tone: "casual",
      starts_at: "2026-10-25T15:00:00Z",
      member_count: 42,
      joined: false,
      tag: "TEAM EVENT",
      description: "Form a 3–4 person squad for HackTX. Matched by skills and vibe.",
      location: "UT Austin · GDC",
    },
    {
      event_id: "evt_study",
      name: "Study buddies",
      type: "informal",
      tone: "casual",
      starts_at: "2026-10-26T18:00:00Z",
      member_count: 18,
      joined: false,
      tag: "1:1 CONNECTION",
      description: "Find someone to grind midterms with — no groups, just 1:1 matches.",
      location: "PCL · online",
    },
    {
      event_id: "evt_photo",
      name: "Campus photo walk",
      type: "informal",
      tone: "casual",
      starts_at: "2026-10-27T17:30:00Z",
      member_count: 11,
      joined: false,
      tag: "CASUAL GROUP",
      description: "Golden-hour walk around the Tower. Bring any camera.",
      location: "Main Mall",
    },
    {
      event_id: "evt_coffee",
      name: "Coffee & vinyl",
      type: "informal",
      tone: "casual",
      starts_at: "2026-10-28T19:00:00Z",
      member_count: 9,
      joined: false,
      tag: "SOCIAL",
      description: "Low-key hang at a local shop. Swap playlists and meet people.",
      location: "Guadalupe",
    },
  ],
};

export const mockEvents: Record<string, EventDetail> = {
  evt_hacktx: {
    event_id: "evt_hacktx",
    org_id: "org_ut",
    name: "HackTX team-up",
    description: "Find your hackathon team. Mutual consent before anything forms.",
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
      {
        question_id: "q_2",
        text: "What do you want to build?",
        kind: "text",
        options: null,
        required: false,
      },
      {
        question_id: "q_3",
        text: "Weekend energy?",
        kind: "single_choice",
        options: ["chill builder", "competitive", "explore & learn"],
        required: true,
      },
    ],
    interview_enabled: true,
    starts_at: "2026-10-25T15:00:00Z",
    created_at: "2026-10-24T20:00:00Z",
    share_url: "https://squadup.tech/events/evt_hacktx",
    host: { user_id: "usr_elena", name: "Elena Brooks" },
    my_membership: null,
    stats: { member_count: 42, groups_formed: 3 },
  },
  evt_study: {
    event_id: "evt_study",
    org_id: "org_ut",
    name: "Study buddies",
    description: "1:1 connections for studying — no groups.",
    type: "informal",
    tone: "casual",
    group_count: null,
    min_size: null,
    max_size: null,
    max_groups_per_user: null,
    required_fields: ["subjects"],
    questions: [
      {
        question_id: "q_s1",
        text: "What are you studying?",
        kind: "text",
        options: null,
        required: true,
      },
    ],
    interview_enabled: false,
    starts_at: "2026-10-26T18:00:00Z",
    created_at: "2026-10-24T18:00:00Z",
    share_url: "https://squadup.tech/events/evt_study",
    host: { user_id: "usr_jordan", name: "Jordan Lee" },
    my_membership: null,
    stats: { member_count: 18, groups_formed: 0 },
  },
};

export const mockRecommendations: RecommendationsResponse = {
  ranked_by: "agent",
  results: [
    {
      candidate_type: "group",
      id: "grp_pixel",
      name: "Pixel Pioneers",
      score: 0.91,
      reason:
        "Looking for a frontend/React person; your climate-apps interest lines up with their product angle.",
      subtitle: "HackTX · 3 of 4 members",
      tags: ["frontend", "product", "casual"],
      member_count: "3/4",
    },
    {
      candidate_type: "user",
      id: "usr_ben",
      name: "Ben Li",
      score: 0.86,
      reason: "Backend + ML overlap; both want an ambitious but friendly weekend pace.",
      subtitle: "CS junior · backend/ML",
      tags: ["backend", "ml"],
    },
    {
      candidate_type: "group",
      id: "grp_lens",
      name: "Lens & Light",
      score: 0.78,
      reason: "Creative side project energy — good backup if Pixel Pioneers fills up.",
      subtitle: "HackTX · 2 of 4 members",
      tags: ["design", "story"],
      member_count: "2/4",
    },
  ],
};

export const mockRequests: RequestItem[] = [
  {
    request_id: "req_1",
    direction: "incoming",
    target_type: "user",
    target_id: "usr_maya",
    target_name: "Pixel Pioneers → you",
    status: "pending",
    preview: "Want to chat about joining our HackTX squad?",
    created_at: "2026-10-25T01:10:00Z",
    thread_id: "thr_1",
  },
  {
    request_id: "req_2",
    direction: "outgoing",
    target_type: "group",
    target_id: "grp_pixel",
    target_name: "Pixel Pioneers",
    status: "pending",
    preview: "You requested to join · awaiting mutual accept",
    created_at: "2026-10-25T01:05:00Z",
    thread_id: "thr_1",
  },
];

export const mockThread: Thread = {
  thread_id: "thr_1",
  title: "Pixel Pioneers · Pre-join chat",
  call_url: "https://meet.jit.si/squadup-pixel-pioneers",
  messages: [
    {
      message_id: "msg_1",
      sender_id: "usr_jordan",
      sender_name: "Jordan Lee",
      text: "Hey Maya! We're building a campus matching tool — would love a React person.",
      created_at: "2026-10-25T01:06:00Z",
    },
    {
      message_id: "msg_2",
      sender_id: "usr_maya",
      sender_name: "Maya Chen",
      text: "That sounds perfect. I'm free for a quick call if you want.",
      created_at: "2026-10-25T01:08:00Z",
    },
  ],
};

export const mockGroup: GroupPage = {
  group_id: "grp_pixel",
  name: "Pixel Pioneers",
  event_id: "evt_hacktx",
  event_name: "HackTX team-up",
  thread_id: "thr_1",
  members: [
    {
      user_id: "usr_jordan",
      name: "Jordan Lee",
      role: "Backend",
      summary: "Wants a chill but ambitious team.",
      contacts: [
        { kind: "discord", value: "jordan#4411" },
        { kind: "phone", value: "+1 512-555-0142" },
      ],
    },
    {
      user_id: "usr_pp",
      name: "Priya Patel",
      role: "ML",
      summary: "Climate + NLP nerd.",
      contacts: [{ kind: "github", value: "priyapatel" }],
    },
    {
      user_id: "usr_maya",
      name: "Maya Chen",
      role: "Frontend",
      summary: "React · product polish.",
      contacts: [
        { kind: "discord", value: "maya#2048" },
        { kind: "github", value: "mayachen" },
      ],
    },
  ],
};

export const mockConnections: Connection[] = [
  {
    user_id: "usr_sam",
    name: "Sam Ortiz",
    reason: "Both grinding discrete math midterms this week.",
    tags: ["CS 331", "evening"],
  },
  {
    user_id: "usr_riley",
    name: "Riley Kim",
    reason: "Prefers quiet library sessions and shared notes.",
    tags: ["PCL", "notes"],
  },
];

export const mockProfile: Profile = {
  user_id: "usr_maya",
  name: "Maya Chen",
  email: "maya@utexas.edu",
  summary:
    "Frontend-focused builder who loves climate apps; wants a chill but ambitious HackTX team.",
  traits: {
    working_style: "pairing",
    ambition: "win",
    availability: "all weekend",
  },
  contacts: [
    { kind: "discord", value: "maya#2048" },
    { kind: "phone", value: "+1 512-555-0199" },
  ],
  socials: [
    { kind: "github", value: "mayachen" },
    { kind: "instagram", value: "@maya.builds" },
  ],
};

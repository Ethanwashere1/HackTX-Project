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

export type Me = {
  user_id: string;
  name: string;
  email: string;
  avatar_url?: string | null;
  orgs: { org_id: string; name: string }[];
  contacts: Contact[];
};

export type OrgFeedEvent = {
  event_id: string;
  name: string;
  type: EventType;
  tone: Tone;
  starts_at?: string | null;
  member_count: number;
  joined: boolean;
  tag?: string;
  description?: string;
  location?: string;
};

export type OrgFeed = {
  org_id: string;
  name: string;
  events: OrgFeedEvent[];
};

export type Question = {
  question_id: string;
  text: string;
  kind: QuestionKind;
  options: string[] | null;
  required: boolean;
};

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

export type Recommendation = {
  candidate_type: "user" | "group";
  id: string;
  name: string;
  score: number;
  reason: string;
  subtitle?: string;
  tags?: string[];
  member_count?: string;
};

export type RecommendationsResponse = {
  ranked_by: "similarity" | "agent";
  results: Recommendation[];
};

export type RequestItem = {
  request_id: string;
  direction: "incoming" | "outgoing";
  target_type: RequestTargetType;
  target_id: string;
  target_name: string;
  status: RequestStatus;
  preview: string;
  created_at: string;
  thread_id?: string;
};

export type Message = {
  message_id: string;
  sender_id: string;
  sender_name: string;
  text: string;
  created_at: string;
};

export type Thread = {
  thread_id: string;
  title: string;
  call_url: string;
  messages: Message[];
};

export type GroupMember = {
  user_id: string;
  name: string;
  role?: string;
  summary?: string;
  contacts?: Contact[];
};

export type GroupPage = {
  group_id: string;
  name: string;
  event_id: string;
  event_name: string;
  members: GroupMember[];
  thread_id: string;
  /** Earliest member — treated as squad owner/founder. */
  owner_user_id?: string | null;
};

export type Connection = {
  user_id: string;
  name: string;
  reason: string;
  tags: string[];
};

export type Profile = {
  user_id: string;
  name: string;
  email: string;
  summary?: string;
  traits?: Record<string, string>;
  contacts: Contact[];
  socials: Contact[];
};

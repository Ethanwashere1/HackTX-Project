import type { Org } from "./types";

const VERIFICATION_COPY: Record<Org["verification"], string> = {
  manual: "An admin approves each request.",
  email_domain: "Auto-approved for matching school emails; others wait for an admin.",
  roster: "Auto-approved if your email is on the member list; others wait for an admin.",
};

export function verificationCopy(org: Org): string {
  if (org.verification === "email_domain" && org.email_domains.length) {
    return `Auto-approved for @${org.email_domains.join(", @")} emails; others wait for an admin.`;
  }
  return VERIFICATION_COPY[org.verification];
}

export function formatWhen(iso: string | null | undefined, fallback = "TBD"): string {
  if (!iso) return fallback;
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Traits are any JSON object (the agents send `{"highlights": [...]}`): flatten for badges. */
export function traitBadges(traits: Record<string, unknown> | null): string[] {
  if (!traits) return [];
  const out: string[] = [];
  for (const [k, v] of Object.entries(traits)) {
    if (Array.isArray(v)) out.push(...v.map((x) => (typeof x === "string" ? x : JSON.stringify(x))));
    else if (v !== null && typeof v === "object") out.push(`${k}: ${JSON.stringify(v)}`);
    else if (v !== null && v !== undefined && v !== "") out.push(`${k}: ${String(v)}`);
  }
  return out;
}

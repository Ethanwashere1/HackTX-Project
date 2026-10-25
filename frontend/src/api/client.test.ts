import { beforeEach, describe, expect, it } from "vitest";
import { api, SEED_USERS } from "./client";

describe("api client (mocks)", () => {
  beforeEach(async () => {
    await api.logout();
  });

  it("uses mocks in tests (VITE_USE_MOCKS=1)", () => {
    expect(api.useMocks()).toBe(true);
  });

  it("returns null me when logged out", async () => {
    expect(await api.me()).toBeNull();
  });

  it("dev login then me", async () => {
    const me = await api.devLogin(SEED_USERS[0]);
    expect(me.name).toBe(SEED_USERS[0].name);
    expect(await api.me()).toMatchObject({ user_id: "usr_maya", email: SEED_USERS[0].email });
  });

  it("loads org feed, and recommendations after joining", async () => {
    await api.devLogin(SEED_USERS[0]);
    const feed = await api.orgFeed("org_ut");
    expect(feed.name).toBe("UT Austin");
    expect(feed.events.length).toBeGreaterThan(0);

    await expect(api.recommendations("evt_hacktx")).rejects.toMatchObject({ status: 403 });
    await api.joinEvent("evt_hacktx", { answers: [], fields: {}, socials: [] });
    const recs = await api.recommendations("evt_hacktx");
    expect(recs.ranked_by).toBe("gemini");
    expect(recs.groups[0]?.name).toBe("Squad Neural");
    expect(recs.people.map((p) => p.name)).toContain("Ben Li");
    // Own squad (Squad Pixel) is never recommended for re-join
    expect(recs.groups.map((g) => g.group_id)).not.toContain("grp_pixel");
  });

  it("returns the AI profile overview", async () => {
    await api.devLogin(SEED_USERS[0]);
    const profile = await api.getProfile();
    expect(profile.overview).toMatch(/builder/i);
  });

  it("suggests valid questionnaire questions, skipping existing ones", async () => {
    await api.devLogin(SEED_USERS[0]);
    const res = await api.suggestQuestions({
      name: "HackTX",
      type: "structured",
      tone: "casual",
      existing_questions: [
        { text: "Describe a project you're proud of.", kind: "text", options: null, required: false },
      ],
      count: 2,
    });
    expect(res.questions).toHaveLength(2);
    expect(res.questions.map((qn) => qn.text)).not.toContain("Describe a project you're proud of.");
    for (const qn of res.questions) {
      const choice = qn.kind === "single_choice" || qn.kind === "multi_choice";
      if (choice) expect(qn.options?.length).toBeGreaterThan(0);
      else expect(qn.options).toBeNull();
    }
  });

  it("marks the squad owner on the squad page", async () => {
    await api.devLogin(SEED_USERS[0]);
    const group = await api.getGroup("grp_pixel");
    expect(group.owner_user_id).toBe(group.members[0]?.user_id);
  });
});

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
    expect(recs.groups[0]?.name).toBe("Team Neural");
    expect(recs.people.length).toBeGreaterThan(0);
  });
});

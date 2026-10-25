import { beforeEach, describe, expect, it } from "vitest";
import { api } from "./client";

describe("api client (mocks)", () => {
  beforeEach(async () => {
    await api.logout();
  });

  it("uses mocks by default", () => {
    expect(api.useMocks()).toBe(true);
  });

  it("returns null me when logged out", async () => {
    expect(await api.me()).toBeNull();
  });

  it("dev login then me", async () => {
    const me = await api.devLogin();
    expect(me.name).toBe("Maya Chen");
    expect(await api.me()).toMatchObject({ user_id: "usr_maya" });
  });

  it("loads org feed and recommendations", async () => {
    await api.devLogin();
    const feed = await api.orgFeed("org_ut");
    expect(feed.events.length).toBeGreaterThan(0);
    const recs = await api.recommendations("evt_hacktx");
    expect(recs.results.map((r) => r.name)).toContain("Ben Li");
    // Own squad (Pixel Pioneers) is not recommended for re-join
    expect(recs.results.map((r) => r.id)).not.toContain("grp_pixel");
  });
});

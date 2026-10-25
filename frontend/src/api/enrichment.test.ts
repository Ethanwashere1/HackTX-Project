import { beforeEach, describe, expect, it } from "vitest";
import { api, SEED_USERS } from "./client";

describe("enrichmentContext", () => {
  beforeEach(async () => {
    await api.devLogin(SEED_USERS[0]);
  });

  it("returns Maps, calendar, social, and location signals from demo SerpAPI shape", async () => {
    const ctx = await api.enrichmentContext({
      lat: 30.2849,
      lng: -97.7341,
    });
    expect(ctx.maps.engine).toBe("google_maps");
    expect(ctx.calendar.engine).toBe("google_events");
    expect(ctx.maps.results.length).toBeGreaterThan(0);
    expect(ctx.calendar.results.length).toBeGreaterThan(0);
    expect(ctx.social.result.handle).toBeTruthy();
    expect(ctx.location.lat).toBeCloseTo(30.2849);
    expect(ctx.location.lng).toBeCloseTo(-97.7341);
  });
});

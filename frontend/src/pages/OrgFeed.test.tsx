import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { api, SEED_USERS } from "../api/client";

describe("OrgFeedPage", () => {
  beforeEach(async () => {
    await api.devLogin(SEED_USERS[0]);
    window.history.pushState({}, "", "/orgs/org_ut");
  });

  afterEach(() => {
    cleanup();
  });

  it("renders UT Austin events from mocks", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/HackTX team-up/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Study buddies/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create event/i })).toBeInTheDocument();
  });

  it("exposes sidebar and mobile navigation landmarks", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/HackTX team-up/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    // Bottom nav is display:none on desktop (correctly omitted from the a11y tree)
    // but remains in the DOM for phone breakpoints.
    const mobileNav = document.querySelector('nav[aria-label="Mobile"]');
    expect(mobileNav).toBeTruthy();
    expect(mobileNav?.querySelectorAll("a").length).toBeGreaterThanOrEqual(4);
  });
});

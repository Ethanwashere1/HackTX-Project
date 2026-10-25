import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { api } from "../api/client";
import { mockEvents, mockMe } from "../demo";

describe("Host cannot join own event", () => {
  beforeEach(async () => {
    await api.devLogin();
    // Make the signed-in user the host of the demo HackTX event
    mockEvents.evt_hacktx.host = { user_id: mockMe.user_id, name: mockMe.name };
    mockEvents.evt_hacktx.my_membership = null;
    window.history.pushState({}, "", "/events/evt_hacktx");
  });

  afterEach(() => {
    cleanup();
    mockEvents.evt_hacktx.host = { user_id: "usr_elena", name: "Elena Brooks" };
  });

  it("hides Join and explains host ownership", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/you’re the host/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: /join event/i })).not.toBeInTheDocument();
  });

  it("rejects joinEvent API calls from the host", async () => {
    await expect(api.joinEvent("evt_hacktx", { answers: [], fields: {}, socials: [] })).rejects.toThrow(
      /host/i,
    );
  });
});

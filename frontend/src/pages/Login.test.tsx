import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { api } from "../api/client";

describe("LoginPage", () => {
  beforeEach(async () => {
    await api.logout();
    window.history.pushState({}, "", "/login");
  });

  afterEach(() => {
    cleanup();
  });

  it("shows SquadUp brand and Google CTA", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: /find your squad/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
  });

  it("signs in with mock Google and reaches the org feed", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /continue with google/i }));
    await waitFor(() => {
      expect(screen.getByText(/HackTX team-up/i)).toBeInTheDocument();
    });
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { api, SEED_USERS } from "../api/client";

describe("CreateEventPage questionnaire count", () => {
  beforeEach(async () => {
    await api.devLogin(SEED_USERS[0]);
    window.history.pushState({}, "", "/events/new");
  });

  afterEach(() => {
    cleanup();
  });

  it("lets the host set how many questions are available", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: /create event/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/number of questions/i)).toHaveValue(3);

    await user.clear(screen.getByLabelText(/number of questions/i));
    await user.type(screen.getByLabelText(/number of questions/i), "5");
    expect(screen.getByText("Question 5")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /remove last/i }));
    expect(screen.queryByText("Question 5")).not.toBeInTheDocument();
    expect(screen.getByText("Question 4")).toBeInTheDocument();
  });

  it("appends AI-suggested questions that stay editable", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: /create event/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /suggest questions/i }));
    expect(await screen.findByText("Question 6")).toBeInTheDocument();
    expect(screen.getByDisplayValue("What role would you take on a squad?")).toBeInTheDocument();
    expect(screen.getByLabelText(/number of questions/i)).toHaveValue(6);
  });
});

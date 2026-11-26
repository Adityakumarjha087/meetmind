import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerText, AskChat } from "@/components/ask-chat";
import { api, ApiError } from "@/lib/api";

const citation = {
  index: 1,
  meeting_id: "m1",
  meeting_title: "Q3 Launch Planning",
  start_s: 32.5,
  end_s: 50,
  speakers: ["Priya"],
  text: "We decided to keep the pricing at twenty nine dollars.",
  score: 0.4,
};

describe("AnswerText", () => {
  it("turns citation markers into timestamp links", () => {
    render(<AnswerText text="Pricing stays at $29 [1]. Unknown [7]." citations={[citation]} />);
    const link = screen.getByRole("link", { name: /Source 1: Q3 Launch Planning at 00:32/ });
    expect(link).toHaveAttribute("href", "/meetings/m1?t=32");
    expect(screen.getByText(/Unknown \[7\]/)).toBeInTheDocument();
  });
});

describe("AskChat", () => {
  it("asks a question and lists sources", async () => {
    const spy = vi.spyOn(api, "ask").mockResolvedValue({ answer: "Pricing is $29 [1].", citations: [citation], engine: "offline" });
    render(<AskChat workspaceId="w1" />);
    await userEvent.type(screen.getByLabelText("Question"), "What about pricing?");
    await userEvent.click(screen.getByRole("button", { name: "Send question" }));
    expect(spy).toHaveBeenCalledWith("w1", "What about pricing?");
    expect(await screen.findByTestId("answer")).toHaveTextContent("Pricing is $29");
    expect(screen.getByRole("list", { name: "Sources" })).toHaveTextContent("Q3 Launch Planning · 00:32");
  });

  it("supports suggestions and shows errors", async () => {
    vi.spyOn(api, "ask").mockRejectedValue(new ApiError(429, "rate_limited", "Too many requests"));
    render(<AskChat workspaceId="w1" />);
    await userEvent.click(screen.getByRole("button", { name: "What did we decide about pricing?" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
  });
});

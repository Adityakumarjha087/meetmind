import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InsightsPanel } from "@/components/insights-panel";
import { PipelineProgress } from "@/components/pipeline-progress";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { insights, item } from "@/test/fixtures";

describe("InsightsPanel", () => {
  it("renders summary, decisions, questions, sentiment and items", async () => {
    const onSeek = vi.fn();
    const onToggle = vi.fn();
    render(<InsightsPanel insights={insights} items={[item()]} onSeek={onSeek} onToggleItem={onToggle} canEdit />);
    expect(screen.getByText("The team planned the Q3 launch.")).toBeInTheDocument();
    expect(screen.getByText("map-reduce · 3 parts")).toBeInTheDocument();
    expect(screen.getByText("Launch on September 15.")).toBeInTheDocument();
    expect(screen.getByText("Enough support staff?")).toBeInTheDocument();
    expect(screen.getByText(/negative -0.30/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Jump to 00:58" }));
    expect(onSeek).toHaveBeenCalledWith(58.7);
    await userEvent.click(screen.getByRole("checkbox", { name: /Fix the payment bugs/ }));
    expect(onToggle).toHaveBeenCalled();
  });

  it("disables checkboxes for viewers", () => {
    render(<InsightsPanel insights={{ ...insights, decisions: [], open_questions: [] }} items={[item()]} canEdit={false} />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText("No explicit decisions were detected.")).toBeInTheDocument();
  });
});

describe("status & progress", () => {
  it("shows pipeline stages and percent", () => {
    render(<PipelineProgress stage="diarize" progress={45} message="Identifying speakers" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "45");
    expect(screen.getByText("Identifying speakers")).toBeInTheDocument();
    expect(screen.getByText("Diarize").closest("li")).toHaveClass("text-primary");
  });

  it("maps statuses to labels", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("renders loading/empty/error states", async () => {
    const retry = vi.fn();
    render(
      <>
        <LoadingState label="Loading things" />
        <EmptyState title="Nothing" description="Add one" />
        <ErrorState message="Boom" onRetry={retry} />
      </>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading things");
    expect(screen.getByText("Nothing")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });
});

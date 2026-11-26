import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SpeakerChips, TranscriptView } from "@/components/transcript-view";
import { segments, speakers } from "@/test/fixtures";

describe("TranscriptView", () => {
  it("seeks to the clicked sentence and highlights the active one", async () => {
    const onSeek = vi.fn();
    render(<TranscriptView segments={segments} speakers={speakers} currentTime={7} onSeek={onSeek} />);
    const rows = screen.getAllByRole("button");
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(rows[0]).not.toHaveAttribute("aria-current");
    await userEvent.click(screen.getByText("Let's plan the launch."));
    expect(onSeek).toHaveBeenCalledWith(0.5);
    expect(screen.getByText("00:06")).toBeInTheDocument();
  });

  it("uses the latest speaker names", () => {
    const renamed = speakers.map((s) => (s.id === "s2" ? { ...s, display_name: "Marcus" } : s));
    render(<TranscriptView segments={segments} speakers={renamed} currentTime={0} onSeek={() => {}} />);
    expect(screen.getByText("Marcus")).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<TranscriptView segments={[]} speakers={[]} currentTime={0} onSeek={() => {}} />);
    expect(screen.getByText("No transcript yet.")).toBeInTheDocument();
  });
});

describe("SpeakerChips", () => {
  it("renames a speaker", async () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(<SpeakerChips speakers={speakers} editable onRename={onRename} />);
    await userEvent.click(screen.getByRole("button", { name: "Rename Speaker 2" }));
    const input = screen.getByLabelText("New name for Speaker 2");
    await userEvent.clear(input);
    await userEvent.type(input, "Marcus{enter}");
    expect(onRename).toHaveBeenCalledWith(speakers[1], "Marcus");
  });

  it("hides rename for read-only users", () => {
    render(<SpeakerChips speakers={speakers} editable={false} onRename={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Rename/ })).not.toBeInTheDocument();
  });
});

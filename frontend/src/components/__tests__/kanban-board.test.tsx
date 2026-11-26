import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { KanbanBoard } from "@/components/kanban-board";
import { item } from "@/test/fixtures";

const items = [
  item({ id: "a", title: "Fix the payment bugs" }),
  item({ id: "b", title: "Send press release", status: "in_progress", owner_name: "Raj", due_date: "2020-01-01" }),
  item({ id: "c", title: "Book webinar", status: "done", position: 3 }),
];

function setup(editable = true) {
  const handlers = {
    onUpdate: vi.fn().mockResolvedValue(undefined),
    onCreate: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
  };
  render(<KanbanBoard items={items} members={[{ user_id: "u1", email: "a@x.com", name: "Alex", role: "member" }]} editable={editable} {...handlers} />);
  return handlers;
}

describe("KanbanBoard", () => {
  it("renders items into their columns with counts", () => {
    setup();
    expect(within(screen.getByTestId("column-todo")).getByText("Fix the payment bugs")).toBeInTheDocument();
    expect(within(screen.getByTestId("column-in_progress")).getByText("Send press release")).toBeInTheDocument();
    expect(within(screen.getByTestId("column-done")).getByText("Book webinar")).toBeInTheDocument();
    expect(screen.getByText(/Overdue/)).toBeInTheDocument();
  });

  it("moves an item via the keyboard-accessible status select", async () => {
    const { onUpdate } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Status for Fix the payment bugs"), "done");
    expect(onUpdate).toHaveBeenCalledWith(items[0], { status: "done", position: 4 });
  });

  it("moves an item with drag and drop", () => {
    const { onUpdate } = setup();
    const card = screen.getByText("Fix the payment bugs").closest("article")!;
    fireEvent.dragStart(card);
    const target = screen.getByTestId("column-in_progress");
    fireEvent.dragOver(target);
    fireEvent.drop(target);
    expect(onUpdate).toHaveBeenCalledWith(items[0], expect.objectContaining({ status: "in_progress" }));
  });

  it("creates, edits and deletes tasks", async () => {
    const { onCreate, onDelete, onUpdate } = setup();
    await userEvent.type(screen.getByLabelText("New task"), "Write FAQ{enter}");
    expect(onCreate).toHaveBeenCalledWith("Write FAQ");
    await userEvent.click(screen.getByRole("button", { name: "Delete Book webinar" }));
    expect(onDelete).toHaveBeenCalledWith(items[2]);
    await userEvent.click(screen.getByRole("button", { name: "Edit Fix the payment bugs" }));
    await userEvent.selectOptions(screen.getByLabelText("Assign to member"), "u1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onUpdate).toHaveBeenCalledWith(items[0], expect.objectContaining({ assignee_id: "u1", title: "Fix the payment bugs" }));
  });

  it("is read-only for viewers", () => {
    setup(false);
    expect(screen.queryByLabelText("New task")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });
});

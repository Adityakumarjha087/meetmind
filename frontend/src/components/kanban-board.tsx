"use client";

import { Clock, Pencil, Plus, Trash } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, NativeSelect } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ActionItem, ActionStatus, Member } from "@/lib/types";
import { cn, formatDay } from "@/lib/utils";

export const COLUMNS: { key: ActionStatus; label: string }[] = [
  { key: "todo", label: "To do" },
  { key: "in_progress", label: "In progress" },
  { key: "done", label: "Done" },
];

export type ItemPatch = Partial<Pick<ActionItem, "title" | "owner_name" | "assignee_id" | "due_date" | "status" | "position">>;

function isOverdue(item: ActionItem): boolean {
  if (!item.due_date || item.status === "done") return false;
  return item.due_date < new Date().toISOString().slice(0, 10);
}

function EditDialog({
  item,
  members,
  onClose,
  onSave,
}: {
  item: ActionItem;
  members: Member[];
  onClose: () => void;
  onSave: (patch: ItemPatch) => Promise<void>;
}) {
  const [title, setTitle] = useState(item.title);
  const [owner, setOwner] = useState(item.owner_name ?? "");
  const [assignee, setAssignee] = useState(item.assignee_id ?? "");
  const [due, setDue] = useState(item.due_date ?? "");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit action item</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            await onSave({
              title: title.trim() || item.title,
              owner_name: owner.trim() || null,
              assignee_id: assignee || null,
              due_date: due || null,
            });
            onClose();
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="ai-title">Title</Label>
            <Input id="ai-title" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={500} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="ai-owner">Owner</Label>
              <Input id="ai-owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="ai-due">Due date</Label>
              <Input id="ai-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="ai-assignee">Assign to member</Label>
            <NativeSelect id="ai-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Unassigned</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <Button type="submit">Save</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function KanbanBoard({
  items,
  members,
  editable,
  onUpdate,
  onCreate,
  onDelete,
}: {
  items: ActionItem[];
  members: Member[];
  editable: boolean;
  onUpdate: (item: ActionItem, patch: ItemPatch) => Promise<void>;
  onCreate: (title: string) => Promise<void>;
  onDelete: (item: ActionItem) => Promise<void>;
}) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<ActionStatus | null>(null);
  const [editing, setEditing] = useState<ActionItem | null>(null);
  const [newTitle, setNewTitle] = useState("");

  async function moveTo(item: ActionItem, status: ActionStatus) {
    if (item.status === status) return;
    const maxPos = Math.max(0, ...items.filter((i) => i.status === status).map((i) => i.position));
    await onUpdate(item, { status, position: maxPos + 1 });
  }

  return (
    <>
      {editable && (
        <form
          className="mb-4 flex gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!newTitle.trim()) return;
            await onCreate(newTitle.trim());
            setNewTitle("");
          }}
        >
          <label htmlFor="new-task" className="sr-only">
            New task
          </label>
          <Input id="new-task" placeholder="Add a task…" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} className="max-w-md" />
          <Button type="submit" variant="secondary">
            <Plus /> Add
          </Button>
        </form>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {COLUMNS.map((col) => {
          const colItems = items.filter((i) => i.status === col.key).sort((a, b) => a.position - b.position);
          return (
            <section
              key={col.key}
              aria-label={col.label}
              data-testid={`column-${col.key}`}
              onDragOver={(e) => {
                if (!editable) return;
                e.preventDefault();
                setOver(col.key);
              }}
              onDragLeave={() => setOver(null)}
              onDrop={async (e) => {
                e.preventDefault();
                setOver(null);
                const item = items.find((i) => i.id === dragging);
                setDragging(null);
                if (item) await moveTo(item, col.key);
              }}
              className={cn(
                "flex min-h-48 flex-col gap-2 rounded-xl border bg-muted/40 p-3 transition-colors",
                over === col.key && "border-primary bg-accent/60",
              )}
            >
              <h2 className="flex items-center justify-between px-1 text-sm font-semibold">
                {col.label}
                <span className="rounded-full bg-card px-2 text-xs font-normal text-muted-foreground">{colItems.length}</span>
              </h2>
              {colItems.length === 0 && <p className="px-1 py-6 text-center text-xs text-muted-foreground">Nothing here</p>}
              {colItems.map((item) => (
                <article
                  key={item.id}
                  draggable={editable}
                  onDragStart={() => setDragging(item.id)}
                  onDragEnd={() => setDragging(null)}
                  className={cn(
                    "group rounded-lg border bg-card p-3 shadow-xs",
                    editable && "cursor-grab active:cursor-grabbing",
                    dragging === item.id && "opacity-50",
                  )}
                >
                  <p className={cn("text-sm font-medium leading-snug", item.status === "done" && "text-muted-foreground line-through")}>
                    {item.title}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {(item.assignee_name || item.owner_name) && <span>{item.assignee_name ?? item.owner_name}</span>}
                    {item.due_date && (
                      <span className={cn("inline-flex items-center gap-1", isOverdue(item) && "font-medium text-destructive")}>
                        <Clock className="size-3" aria-hidden />
                        {isOverdue(item) ? "Overdue · " : ""}
                        {formatDay(item.due_date)}
                      </span>
                    )}
                  </div>
                  {item.meeting_id && (
                    <Link
                      href={`/meetings/${item.meeting_id}${item.source_start_s != null ? `?t=${Math.floor(item.source_start_s)}` : ""}`}
                      className="mt-1 block truncate text-xs text-primary hover:underline"
                    >
                      {item.meeting_title}
                    </Link>
                  )}
                  {editable && (
                    <div className="mt-2 flex items-center gap-1">
                      <label className="sr-only" htmlFor={`status-${item.id}`}>
                        Status for {item.title}
                      </label>
                      <NativeSelect
                        id={`status-${item.id}`}
                        className="h-7 flex-1 text-xs"
                        value={item.status}
                        onChange={(e) => void moveTo(item, e.target.value as ActionStatus)}
                      >
                        {COLUMNS.map((c) => (
                          <option key={c.key} value={c.key}>
                            {c.label}
                          </option>
                        ))}
                      </NativeSelect>
                      <Button size="icon" variant="ghost" className="size-7" aria-label={`Edit ${item.title}`} onClick={() => setEditing(item)}>
                        <Pencil />
                      </Button>
                      <Button size="icon" variant="ghost" className="size-7" aria-label={`Delete ${item.title}`} onClick={() => void onDelete(item)}>
                        <Trash />
                      </Button>
                    </div>
                  )}
                </article>
              ))}
            </section>
          );
        })}
      </div>
      {editing && (
        <EditDialog item={editing} members={members} onClose={() => setEditing(null)} onSave={(patch) => onUpdate(editing, patch)} />
      )}
    </>
  );
}

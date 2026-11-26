"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { KanbanBoard, type ItemPatch } from "@/components/kanban-board";
import { ErrorState, LoadingState } from "@/components/states";
import { NativeSelect } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { canEdit, useAuth } from "@/lib/auth-context";
import type { ActionItem, Member } from "@/lib/types";

export default function BoardPage() {
  const { workspace } = useAuth();
  const wsId = workspace!.id;
  const [items, setItems] = useState<ActionItem[] | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [filter, setFilter] = useState<"all" | "me">("all");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, mem] = await Promise.all([
        api.actionItems(wsId, filter === "me" ? { assignee: "me" } : {}),
        api.members(wsId),
      ]);
      setItems(list);
      setMembers(mem);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load tasks");
    }
  }, [wsId, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  async function update(item: ActionItem, patch: ItemPatch) {
    setItems((list) => list?.map((i) => (i.id === item.id ? { ...i, ...patch } : i)) ?? list);
    try {
      const saved = await api.updateActionItem(item.id, patch);
      setItems((list) => list?.map((i) => (i.id === item.id ? saved : i)) ?? list);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Update failed");
      void load();
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Task board</h1>
          <p className="text-sm text-muted-foreground">Action items extracted from every meeting. Drag cards between columns.</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="board-filter" className="text-sm text-muted-foreground">
            Show
          </label>
          <NativeSelect id="board-filter" value={filter} onChange={(e) => setFilter(e.target.value as "all" | "me")}>
            <option value="all">All tasks</option>
            <option value="me">Assigned to me</option>
          </NativeSelect>
        </div>
      </div>
      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items === null ? (
        <LoadingState />
      ) : (
        <KanbanBoard
          items={items}
          members={members}
          editable={canEdit(workspace)}
          onUpdate={update}
          onCreate={async (title) => {
            try {
              const created = await api.createActionItem(wsId, { title });
              setItems((list) => [...(list ?? []), created]);
            } catch (err) {
              toast.error(err instanceof ApiError ? err.message : "Could not add task");
            }
          }}
          onDelete={async (item) => {
            setItems((list) => list?.filter((i) => i.id !== item.id) ?? list);
            try {
              await api.deleteActionItem(item.id);
            } catch {
              toast.error("Delete failed");
              void load();
            }
          }}
        />
      )}
    </div>
  );
}

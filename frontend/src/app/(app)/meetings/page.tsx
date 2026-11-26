"use client";

import { AudioLines, CalendarPlus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { UploadDialog } from "@/components/upload-dialog";
import { useProgress } from "@/hooks/use-progress";
import { api, ApiError } from "@/lib/api";
import { canEdit, useAuth } from "@/lib/auth-context";
import type { MeetingSummary } from "@/lib/types";
import { formatDate, formatDuration } from "@/lib/utils";

export default function MeetingsPage() {
  const { workspace } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<MeetingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const wsId = workspace!.id;

  const load = useCallback(async () => {
    try {
      setError(null);
      setItems((await api.meetings(wsId, { q: q.trim() || undefined })).items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load meetings");
    }
  }, [wsId, q]);

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  useProgress({ workspaceId: wsId }, (ev) =>
    setItems((prev) => prev?.map((m) => (m.id === ev.meeting_id ? { ...m, ...ev } : m)) ?? prev),
  );

  // Polling fallback while something is processing (e.g. websocket blocked by a proxy).
  const busy = items?.some((m) => m.status === "processing" || m.status === "queued");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [busy, load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Meetings</h1>
          <p className="text-sm text-muted-foreground">Recordings, transcripts and AI notes for {workspace!.name}</p>
        </div>
        {canEdit(workspace) && <UploadDialog workspaceId={wsId} onUploaded={(m) => router.push(`/meetings/${m.id}`)} />}
      </div>
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input aria-label="Search meetings" placeholder="Search by title…" className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items === null ? (
        <div className="grid gap-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={AudioLines}
          title={q ? "No meetings match your search" : "No meetings yet"}
          description={q ? undefined : "Upload a recording or record one in the browser to get a transcript, summary and action items."}
          action={!q && canEdit(workspace) ? <UploadDialog workspaceId={wsId} onUploaded={(m) => router.push(`/meetings/${m.id}`)} /> : undefined}
        />
      ) : (
        <ul className="grid gap-3" data-testid="meeting-list">
          {items.map((m) => (
            <li key={m.id}>
              <Link href={`/meetings/${m.id}`} className="block">
                <Card className="flex flex-wrap items-center gap-4 p-4 transition-colors hover:bg-muted/50">
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
                    {m.status === "scheduled" ? <CalendarPlus className="size-5" aria-hidden /> : <AudioLines className="size-5" aria-hidden />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{m.title}</p>
                    <p className="text-sm text-muted-foreground">
                      {formatDate(m.scheduled_at ?? m.created_at)} · {formatDuration(m.duration_s)}
                      {m.speaker_count > 0 && ` · ${m.speaker_count} speakers`}
                      {m.action_item_count > 0 && ` · ${m.action_item_count} action items`}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {(m.status === "processing" || m.status === "queued") && (
                      <span className="text-xs tabular-nums text-muted-foreground">{m.progress}%</span>
                    )}
                    <StatusBadge status={m.status} />
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

"use client";

import { ArrowLeft, Download, Link as LinkIcon, RefreshCw, Send, Trash } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { InsightsPanel } from "@/components/insights-panel";
import { PipelineProgress } from "@/components/pipeline-progress";
import { ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { SpeakerChips, TranscriptView } from "@/components/transcript-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UploadDialog } from "@/components/upload-dialog";
import { WaveformPlayer, type WaveformHandle } from "@/components/waveform-player";
import { useProgress } from "@/hooks/use-progress";
import { api, ApiError, downloadExport } from "@/lib/api";
import { canEdit, isAdmin, useAuth } from "@/lib/auth-context";
import type { ActionItem, MeetingDetail, Segment, Speaker } from "@/lib/types";
import { formatDate, formatDuration } from "@/lib/utils";

function errMsg(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

export default function MeetingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { workspace } = useAuth();
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [items, setItems] = useState<ActionItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [tab, setTab] = useState("summary");
  const player = useRef<WaveformHandle>(null);
  const initialSeek = useRef<number | null>(null);
  const editable = canEdit(workspace);

  const load = useCallback(async () => {
    try {
      const m = await api.meeting(id);
      setMeeting(m);
      if (m.status === "completed") {
        const [segs, acts] = await Promise.all([api.transcript(id), api.actionItems(m.workspace_id, { meeting_id: id })]);
        setSegments(segs);
        setItems(acts);
      }
      setError(null);
    } catch (err) {
      setError(errMsg(err, "Failed to load meeting"));
    }
  }, [id]);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("t");
    if (t) {
      initialSeek.current = Number(t);
      setTab("transcript");
    }
    void load();
  }, [load]);

  useProgress({ meetingId: id }, (ev) => {
    setMeeting((m) => (m ? { ...m, ...ev } : m));
    if (ev.status === "completed" || ev.status === "failed") void load();
  });

  const processing = meeting?.status === "processing" || meeting?.status === "queued";
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [processing, load]);

  useEffect(() => {
    if (meeting?.audio_url && segments.length && initialSeek.current != null) {
      const t = initialSeek.current;
      initialSeek.current = null;
      setTimeout(() => player.current?.seek(t, false), 300);
      setTime(t);
    }
  }, [meeting?.audio_url, segments.length]);

  const seek = (s: number) => {
    player.current?.seek(s);
    setTime(s);
  };

  async function rename(speaker: Speaker, name: string) {
    try {
      await api.renameSpeaker(id, speaker.id, name);
      toast.success(`Renamed to ${name}`);
      await load();
    } catch (err) {
      toast.error(errMsg(err, "Rename failed"));
    }
  }

  async function toggleItem(item: ActionItem) {
    const status = item.status === "done" ? "todo" : "done";
    setItems((list) => list.map((i) => (i.id === item.id ? { ...i, status } : i)));
    try {
      await api.updateActionItem(item.id, { status });
    } catch (err) {
      toast.error(errMsg(err, "Update failed"));
      void load();
    }
  }

  async function share() {
    try {
      const { share_url } = await api.share(id);
      await navigator.clipboard?.writeText(share_url).catch(() => undefined);
      toast.success("Share link copied", { description: share_url });
      void load();
    } catch (err) {
      toast.error(errMsg(err, "Could not create share link"));
    }
  }

  async function slack() {
    try {
      await api.postToSlack(id);
      toast.success("Summary posted to Slack");
    } catch (err) {
      toast.error(errMsg(err, "Slack post failed"));
    }
  }

  async function reprocess() {
    try {
      await api.reprocess(id);
      toast.message("Reprocessing started");
      void load();
    } catch (err) {
      toast.error(errMsg(err, "Could not reprocess"));
    }
  }

  async function remove() {
    if (!window.confirm("Delete this meeting, its audio and its action items?")) return;
    try {
      await api.deleteMeeting(id);
      toast.success("Meeting deleted");
      router.replace("/meetings");
    } catch (err) {
      toast.error(errMsg(err, "Delete failed"));
    }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!meeting) return <LoadingState label="Loading meeting…" />;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/meetings" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" aria-hidden /> All meetings
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex flex-wrap items-center gap-3 text-2xl font-semibold tracking-tight">
              {meeting.title} <StatusBadge status={meeting.status} />
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {formatDate(meeting.scheduled_at ?? meeting.created_at)} · {formatDuration(meeting.duration_s)}
              {meeting.stt_backend && ` · STT: ${meeting.stt_backend} · diarizer: ${meeting.diarizer_backend}`}
            </p>
          </div>
          {meeting.status === "completed" && (
            <div className="flex flex-wrap gap-2">
              {editable && (
                <Button variant="outline" size="sm" onClick={share}>
                  <LinkIcon /> {meeting.share_url ? "Copy share link" : "Share"}
                </Button>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Download /> Export
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => void downloadExport(id, "md")}>Markdown (.md)</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => void downloadExport(id, "pdf")}>PDF (.pdf)</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              {editable && workspace?.slack_configured && (
                <Button variant="outline" size="sm" onClick={slack}>
                  <Send /> Post to Slack
                </Button>
              )}
              {editable && (
                <Button variant="ghost" size="sm" onClick={reprocess} aria-label="Reprocess meeting">
                  <RefreshCw />
                </Button>
              )}
              {isAdmin(workspace) && (
                <Button variant="ghost" size="sm" onClick={remove} aria-label="Delete meeting">
                  <Trash />
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {meeting.status === "scheduled" && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div>
              <p className="font-medium">Scheduled meeting</p>
              <p className="text-sm text-muted-foreground">
                {meeting.attendees.length ? `Attendees: ${meeting.attendees.join(", ")}` : "Attach the recording once it's done."}
              </p>
            </div>
            {editable && <UploadDialog workspaceId={meeting.workspace_id} meetingId={meeting.id} onUploaded={() => void load()} />}
          </CardContent>
        </Card>
      )}

      {(processing || meeting.status === "failed") && (
        <Card>
          <CardContent className="space-y-3 p-5" data-testid="pipeline-progress">
            <PipelineProgress
              stage={meeting.stage}
              progress={meeting.progress}
              message={meeting.status_message}
              failed={meeting.status === "failed"}
            />
            {meeting.error && (
              <p role="alert" className="text-sm text-destructive">
                {meeting.error}
              </p>
            )}
            {meeting.status === "failed" && editable && meeting.original_filename && (
              <Button variant="outline" size="sm" onClick={reprocess}>
                <RefreshCw /> Retry
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {meeting.status === "completed" && (
        <>
          {meeting.audio_url && (
            <WaveformPlayer
              ref={player}
              url={meeting.audio_url}
              peaks={meeting.waveform_peaks}
              duration={meeting.duration_s}
              onTime={setTime}
            />
          )}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="summary">Summary</TabsTrigger>
              <TabsTrigger value="transcript">Transcript</TabsTrigger>
            </TabsList>
            <TabsContent value="summary">
              {meeting.insights ? (
                <InsightsPanel insights={meeting.insights} items={items} onSeek={seek} onToggleItem={toggleItem} canEdit={editable} />
              ) : (
                <p className="text-sm text-muted-foreground">No AI notes for this meeting.</p>
              )}
            </TabsContent>
            <TabsContent value="transcript" className="space-y-4">
              <SpeakerChips speakers={meeting.speakers} editable={editable} onRename={rename} />
              <Card>
                <CardContent className="p-2">
                  <TranscriptView segments={segments} speakers={meeting.speakers} currentTime={time} onSeek={seek} />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

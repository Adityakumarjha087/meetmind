"use client";

import { Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Recorder } from "@/components/recorder";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import type { MeetingDetail } from "@/lib/types";

const ACCEPT = "audio/*,video/*,.wav,.mp3,.m4a,.webm,.ogg,.flac,.mp4,.mov,.mkv";

export function UploadDialog({
  workspaceId,
  meetingId,
  onUploaded,
  trigger,
}: {
  workspaceId: string;
  meetingId?: string;
  onUploaded: (meeting: MeetingDetail) => void;
  trigger?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState<"upload" | "recording">("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setFile(null);
    setTranscript(null);
    setTitle("");
    setError(null);
    setSource("upload");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Choose or record an audio/video file first.");
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("file", file);
    if (transcript) form.set("transcript", transcript);
    try {
      let meeting: MeetingDetail;
      if (meetingId) {
        meeting = await api.attachAudio(meetingId, form);
      } else {
        if (title.trim()) form.set("title", title.trim());
        form.set("source", source);
        meeting = await api.uploadMeeting(workspaceId, form);
      }
      toast.success("Upload complete — processing started");
      onUploaded(meeting);
      setOpen(false);
      reset();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            <Upload /> New meeting
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{meetingId ? "Attach recording" : "Add a meeting"}</DialogTitle>
          <DialogDescription>Upload audio or video, or record directly in your browser.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {!meetingId && (
            <div className="grid gap-1.5">
              <Label htmlFor="title">Title</Label>
              <Input id="title" placeholder="e.g. Weekly product sync" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
            </div>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="file">Audio or video file</Label>
            <Input
              id="file"
              type="file"
              accept={ACCEPT}
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setSource("upload");
              }}
            />
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
          </div>
          <Recorder
            onRecorded={(f) => {
              setFile(f);
              setSource("recording");
              toast.message(`Recorded ${(f.size / 1024).toFixed(0)} KB`);
            }}
          />
          {file && (
            <p className="truncate text-sm text-muted-foreground">
              Selected: <span className="text-foreground">{file.name}</span>
            </p>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="transcript">
              Transcript <span className="font-normal text-muted-foreground">(optional .vtt, .srt, .json, .txt)</span>
            </Label>
            <Input id="transcript" type="file" accept=".vtt,.srt,.json,.txt" onChange={(e) => setTranscript(e.target.files?.[0] ?? null)} />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? "Uploading…" : "Upload & process"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

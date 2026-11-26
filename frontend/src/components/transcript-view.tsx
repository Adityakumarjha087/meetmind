"use client";

import { Check, Pencil, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Segment, Speaker } from "@/lib/types";
import { cn, formatTimestamp } from "@/lib/utils";

const SPEAKER_COLORS = [
  "text-indigo-600 dark:text-indigo-300",
  "text-emerald-600 dark:text-emerald-300",
  "text-amber-600 dark:text-amber-300",
  "text-rose-600 dark:text-rose-300",
  "text-sky-600 dark:text-sky-300",
  "text-fuchsia-600 dark:text-fuchsia-300",
];

export function SpeakerChips({
  speakers,
  editable,
  onRename,
}: {
  speakers: Speaker[];
  editable: boolean;
  onRename: (speaker: Speaker, name: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Speakers">
      {speakers.map((s, i) => (
        <li key={s.id} className="flex items-center gap-1.5 rounded-full border bg-card py-1 pl-3 pr-1 text-sm">
          {editing === s.id ? (
            <form
              className="flex items-center gap-1"
              onSubmit={async (e) => {
                e.preventDefault();
                if (value.trim()) await onRename(s, value.trim());
                setEditing(null);
              }}
            >
              <Input
                autoFocus
                aria-label={`New name for ${s.display_name}`}
                className="h-7 w-32"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              <Button type="submit" size="icon" variant="ghost" className="size-7" aria-label="Save name">
                <Check />
              </Button>
              <Button type="button" size="icon" variant="ghost" className="size-7" aria-label="Cancel" onClick={() => setEditing(null)}>
                <X />
              </Button>
            </form>
          ) : (
            <>
              <span className={cn("font-medium", SPEAKER_COLORS[i % SPEAKER_COLORS.length])}>{s.display_name}</span>
              <span className="text-xs text-muted-foreground">{formatTimestamp(s.talk_time_s)}</span>
              {editable && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7"
                  aria-label={`Rename ${s.display_name}`}
                  onClick={() => {
                    setEditing(s.id);
                    setValue(s.display_name);
                  }}
                >
                  <Pencil />
                </Button>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export function TranscriptView({
  segments,
  speakers,
  currentTime,
  onSeek,
}: {
  segments: Segment[];
  speakers: Speaker[];
  currentTime: number;
  onSeek: (seconds: number) => void;
}) {
  const colorFor = useMemo(() => {
    const map = new Map(speakers.map((s, i) => [s.id, SPEAKER_COLORS[i % SPEAKER_COLORS.length]]));
    return (id: string | null) => (id ? map.get(id) : undefined) ?? "text-muted-foreground";
  }, [speakers]);
  const nameFor = useMemo(() => new Map(speakers.map((s) => [s.id, s.display_name])), [speakers]);
  const activeIdx = segments.findIndex((s) => currentTime >= s.start_s && currentTime < s.end_s + 0.3);

  if (!segments.length) return <p className="text-sm text-muted-foreground">No transcript yet.</p>;
  return (
    <ol className="space-y-1" aria-label="Transcript">
      {segments.map((seg, i) => (
        <li key={seg.id}>
          <button
            type="button"
            onClick={() => onSeek(seg.start_s)}
            aria-current={i === activeIdx ? "true" : undefined}
            className={cn(
              "group grid w-full cursor-pointer grid-cols-[3.5rem_1fr] gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
              i === activeIdx && "bg-accent",
            )}
          >
            <span className="pt-0.5 font-mono text-xs tabular-nums text-muted-foreground group-hover:text-primary">
              {formatTimestamp(seg.start_s)}
            </span>
            <span className="text-sm leading-relaxed">
              <span className={cn("mr-2 font-semibold", colorFor(seg.speaker_id))}>
                {(seg.speaker_id && nameFor.get(seg.speaker_id)) ?? seg.speaker_name ?? "Unknown"}
              </span>
              {seg.text}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

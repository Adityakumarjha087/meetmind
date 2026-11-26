import { Check, LoaderCircle } from "lucide-react";

import type { PipelineStage } from "@/lib/types";
import { cn } from "@/lib/utils";

export const STAGES: { key: PipelineStage; label: string }[] = [
  { key: "normalize", label: "Normalise" },
  { key: "transcribe", label: "Transcribe" },
  { key: "diarize", label: "Diarize" },
  { key: "merge", label: "Merge" },
  { key: "summarize", label: "Summarise" },
  { key: "index", label: "Index" },
];

export function PipelineProgress({
  stage,
  progress,
  message,
  failed = false,
}: {
  stage: PipelineStage;
  progress: number;
  message?: string | null;
  failed?: boolean;
}) {
  const current = STAGES.findIndex((s) => s.key === stage);
  const done = stage === "done";
  return (
    <div className="space-y-3" aria-label="Processing progress">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{message ?? "Processing"}</span>
        <span className="tabular-nums text-muted-foreground">{progress}%</span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", failed ? "bg-destructive" : "bg-primary")}
          style={{ width: `${Math.max(3, progress)}%` }}
        />
      </div>
      <ol className="grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
        {STAGES.map((s, i) => {
          const complete = done || (current > -1 && i < current);
          const active = !done && i === current && !failed;
          return (
            <li
              key={s.key}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2 py-1",
                complete && "border-success/40 text-success",
                active && "border-primary/50 text-primary",
                !complete && !active && "text-muted-foreground",
              )}
            >
              {complete ? (
                <Check className="size-3" aria-hidden />
              ) : active ? (
                <LoaderCircle className="size-3 animate-spin" aria-hidden />
              ) : (
                <span className="size-3 rounded-full border" aria-hidden />
              )}
              {s.label}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

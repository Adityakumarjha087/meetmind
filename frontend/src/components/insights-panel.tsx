"use client";

import { CircleCheck, Clock, Lightbulb, MessageCircleQuestionMark } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ActionItem, Insights, SpeakerSentiment } from "@/lib/types";
import { cn, formatDay, formatTimestamp } from "@/lib/utils";

function Timestamp({ seconds, onSeek }: { seconds: number | null; onSeek?: (s: number) => void }) {
  if (seconds == null) return null;
  return (
    <button
      type="button"
      onClick={() => onSeek?.(seconds)}
      className="ml-2 cursor-pointer rounded px-1 font-mono text-xs text-primary hover:bg-accent"
      aria-label={`Jump to ${formatTimestamp(seconds)}`}
    >
      {formatTimestamp(seconds)}
    </button>
  );
}

/** Diverging bar per speaker: blue pole for positive, orange pole for negative, neutral midline. */
export function SentimentBars({ data }: { data: SpeakerSentiment[] }) {
  return (
    <ul className="space-y-3" aria-label="Sentiment by speaker">
      {data.map((s) => {
        const pct = Math.min(50, Math.abs(s.score) * 50);
        const positive = s.score >= 0;
        return (
          <li key={s.speaker} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3 text-sm" title={s.rationale ?? undefined}>
            <span className="truncate font-medium">{s.speaker}</span>
            <span className="relative h-3 rounded-sm bg-muted" aria-hidden>
              <span className="absolute inset-y-0 left-1/2 w-px bg-[var(--viz-neutral)]" />
              <span
                className="absolute inset-y-0 rounded-[4px]"
                style={{
                  left: positive ? "50%" : `${50 - pct}%`,
                  width: `${pct}%`,
                  background: positive ? "var(--series-1)" : "var(--series-2)",
                }}
              />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">
              {s.label} {s.score > 0 ? "+" : ""}
              {s.score.toFixed(2)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function InsightsPanel({
  insights,
  items,
  onSeek,
  onToggleItem,
  canEdit,
}: {
  insights: Insights;
  items: ActionItem[];
  onSeek?: (s: number) => void;
  onToggleItem?: (item: ActionItem) => void;
  canEdit?: boolean;
}) {
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Executive summary</CardTitle>
          <div className="flex gap-1.5">
            {insights.strategy === "map_reduce" && <Badge variant="secondary">map-reduce · {insights.chunks_processed} parts</Badge>}
            <Badge variant="outline">{insights.engine}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="leading-relaxed">{insights.executive_summary}</p>
          {insights.topics.length > 0 && (
            <div className="flex flex-wrap gap-1.5" aria-label="Topics">
              {insights.topics.map((t) => (
                <Badge key={t} variant="secondary">
                  {t}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lightbulb className="size-4 text-primary" aria-hidden /> Key decisions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {insights.decisions.length ? (
              <ul className="space-y-2 text-sm">
                {insights.decisions.map((d, i) => (
                  <li key={i} className="leading-relaxed">
                    {d.text}
                    <Timestamp seconds={d.timestamp_s} onSeek={onSeek} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No explicit decisions were detected.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircleQuestionMark className="size-4 text-primary" aria-hidden /> Open questions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {insights.open_questions.length ? (
              <ul className="space-y-2 text-sm">
                {insights.open_questions.map((q, i) => (
                  <li key={i}>
                    {q.text}
                    <Timestamp seconds={q.timestamp_s} onSeek={onSeek} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Nothing left unresolved.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CircleCheck className="size-4 text-primary" aria-hidden /> Action items
          </CardTitle>
        </CardHeader>
        <CardContent>
          {items.length ? (
            <ul className="divide-y" data-testid="action-items">
              {items.map((item) => (
                <li key={item.id} className="flex items-start gap-3 py-2.5">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 accent-[var(--primary)]"
                    checked={item.status === "done"}
                    disabled={!canEdit}
                    onChange={() => onToggleItem?.(item)}
                    aria-label={`Mark "${item.title}" ${item.status === "done" ? "not done" : "done"}`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-sm font-medium", item.status === "done" && "text-muted-foreground line-through")}>
                      {item.title}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                      {item.owner_name && <span>Owner: {item.owner_name}</span>}
                      {item.due_date && (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="size-3" aria-hidden /> Due {formatDay(item.due_date)}
                        </span>
                      )}
                      <Timestamp seconds={item.source_start_s} onSeek={onSeek} />
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No action items were found.</p>
          )}
        </CardContent>
      </Card>

      {insights.sentiment.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Sentiment & talk time by speaker</CardTitle>
          </CardHeader>
          <CardContent>
            <SentimentBars data={insights.sentiment} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

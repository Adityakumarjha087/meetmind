"use client";

import { AudioLines } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SentimentBars } from "@/components/insights-panel";
import { ErrorState, LoadingState } from "@/components/states";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import type { PublicMeeting } from "@/lib/types";
import { formatDate, formatDay, formatDuration } from "@/lib/utils";

export default function SharedMeetingPage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<PublicMeeting | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .publicMeeting(token)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "This link is not available"));
  }, [token]);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <span className="flex items-center gap-2 font-semibold">
          <AudioLines className="size-5 text-primary" aria-hidden /> MeetMind
        </span>
        <ThemeToggle />
      </header>
      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <LoadingState />
      ) : (
        <main className="space-y-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{data.title}</h1>
            <p className="text-sm text-muted-foreground">
              {formatDate(data.scheduled_at ?? data.created_at)} · {formatDuration(data.duration_s)} · {data.speakers.join(", ")}
            </p>
          </div>
          {data.insights && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Summary</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="leading-relaxed">{data.insights.executive_summary}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {data.insights.topics.map((t) => (
                      <Badge key={t} variant="secondary">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
              {data.insights.decisions.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Decisions</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {data.insights.decisions.map((d, i) => (
                        <li key={i}>{d.text}</li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Action items</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="divide-y text-sm">
                {data.action_items.map((a, i) => (
                  <li key={i} className="flex flex-wrap justify-between gap-2 py-2">
                    <span className={a.status === "done" ? "text-muted-foreground line-through" : ""}>{a.title}</span>
                    <span className="text-muted-foreground">
                      {[a.owner_name, a.due_date && `due ${formatDay(a.due_date)}`].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          {data.insights?.sentiment.length ? (
            <Card>
              <CardHeader>
                <CardTitle>Speakers</CardTitle>
              </CardHeader>
              <CardContent>
                <SentimentBars data={data.insights.sentiment} />
              </CardContent>
            </Card>
          ) : null}
        </main>
      )}
    </div>
  );
}

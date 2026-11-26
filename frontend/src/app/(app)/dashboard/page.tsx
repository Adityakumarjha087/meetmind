"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { NativeSelect } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MinutesChart, StageChart, StatTile } from "@/components/usage-charts";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { UsageReport } from "@/lib/types";
import { formatUsd } from "@/lib/utils";

export default function DashboardPage() {
  const { workspace } = useAuth();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api.usage(workspace!.id, days));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load usage");
    }
  }, [workspace, days]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
          <p className="text-sm text-muted-foreground">Minutes transcribed, processing time and cost estimates</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="range" className="text-sm text-muted-foreground">
            Period
          </label>
          <NativeSelect id="range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </NativeSelect>
        </div>
      </div>
      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data ? (
        <LoadingState />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Minutes transcribed" value={data.totals.minutes_transcribed.toFixed(1)} hint={`${data.totals.meetings_processed} meetings`} />
            <StatTile
              label="Avg. processing time"
              value={`${data.totals.avg_processing_seconds.toFixed(1)}s`}
              hint={`${(data.totals.avg_realtime_factor * 100).toFixed(1)}% of audio length`}
            />
            <StatTile label="Actual cost" value={formatUsd(data.totals.cost_usd)} hint={`${formatUsd(data.totals.cost_per_meeting_usd)} per meeting`} />
            <StatTile
              label="Hosted-API estimate"
              value={formatUsd(data.totals.projected_hosted_cost_usd)}
              hint="If run on Whisper API + Claude Opus 5.5"
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <MinutesChart data={data.daily} />
            <StageChart stages={data.stage_seconds} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>By provider</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-muted-foreground">
                  <tr>
                    <th className="py-2 font-medium">Kind</th>
                    <th className="py-2 font-medium">Provider</th>
                    <th className="py-2 text-right font-medium">Calls</th>
                    <th className="py-2 text-right font-medium">Audio min</th>
                    <th className="py-2 text-right font-medium">Tokens in / out</th>
                    <th className="py-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {data.by_provider.map((r) => (
                    <tr key={`${r.kind}-${r.provider}`} className="border-t">
                      <td className="py-2">{r.kind}</td>
                      <td className="py-2">{r.provider}</td>
                      <td className="py-2 text-right">{r.events}</td>
                      <td className="py-2 text-right">{r.audio_minutes.toFixed(1)}</td>
                      <td className="py-2 text-right">
                        {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
                      </td>
                      <td className="py-2 text-right">{formatUsd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

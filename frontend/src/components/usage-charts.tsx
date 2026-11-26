"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { UsageReport } from "@/lib/types";
import { formatDay, formatUsd } from "@/lib/utils";

const AXIS = { fontSize: 11, fill: "var(--muted-foreground)" };

function ChartTooltip({ active, payload, label, unit }: { active?: boolean; payload?: { value: number }[]; label?: string; unit: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium">{label}</p>
      <p className="text-muted-foreground">
        {payload[0].value.toLocaleString(undefined, { maximumFractionDigits: 2 })} {unit}
      </p>
    </div>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export function MinutesChart({ data }: { data: UsageReport["daily"] }) {
  const [table, setTable] = useState(false);
  const rows = data.map((d) => ({ ...d, label: formatDay(d.date), minutes: Number(d.minutes.toFixed(2)) }));
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between">
        <div>
          <CardTitle>Minutes transcribed per day</CardTitle>
          <CardDescription>Audio processed by the pipeline</CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Show chart" : "Show table"}
        </Button>
      </CardHeader>
      <CardContent>
        {table ? (
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 font-medium">Date</th>
                  <th className="py-1 text-right font-medium">Minutes</th>
                  <th className="py-1 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {rows
                  .filter((r) => r.minutes > 0)
                  .map((r) => (
                    <tr key={r.date} className="border-t">
                      <td className="py-1">{r.label}</td>
                      <td className="py-1 text-right">{r.minutes}</td>
                      <td className="py-1 text-right">{formatUsd(r.cost_usd)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="h-64" role="img" aria-label="Bar chart of minutes transcribed per day">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
                <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals />
                <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltip unit="min" />} />
                <Bar dataKey="minutes" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const STAGE_LABELS: Record<string, string> = {
  normalize: "Normalise",
  transcribe: "Transcribe",
  diarize: "Diarize",
  merge: "Merge",
  summarize: "Summarise",
  index: "Index",
};

export function StageChart({ stages }: { stages: Record<string, number> }) {
  const rows = Object.keys(STAGE_LABELS)
    .filter((k) => k in stages)
    .map((k) => ({ label: STAGE_LABELS[k], seconds: Number(stages[k].toFixed(3)) }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Processing time by stage</CardTitle>
        <CardDescription>Total seconds across meetings in this period</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-64" role="img" aria-label="Bar chart of processing seconds per pipeline stage">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
              <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="label" tick={AXIS} tickLine={false} axisLine={false} width={80} />
              <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltip unit="s" />} />
              <Bar dataKey="seconds" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import { Pause, Play } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type WaveSurfer from "wavesurfer.js";

import { Button } from "@/components/ui/button";
import { formatTimestamp } from "@/lib/utils";

export interface WaveformHandle {
  seek: (seconds: number, autoplay?: boolean) => void;
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** WaveSurfer.js player. Uses server-computed peaks so long recordings render instantly. */
export const WaveformPlayer = forwardRef<
  WaveformHandle,
  { url: string; peaks?: number[] | null; duration?: number | null; onTime?: (t: number) => void }
>(function WaveformPlayer({ url, peaks, duration, onTime }, ref) {
  const container = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [ready, setReady] = useState(false);
  const onTimeRef = useRef(onTime);
  onTimeRef.current = onTime;

  useEffect(() => {
    let destroyed = false;
    let instance: WaveSurfer | null = null;
    (async () => {
      const { default: WaveSurferCtor } = await import("wavesurfer.js");
      if (destroyed || !container.current) return;
      instance = WaveSurferCtor.create({
        container: container.current,
        url,
        peaks: peaks?.length ? [peaks] : undefined,
        duration: duration ?? undefined,
        height: 72,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        cursorWidth: 2,
        normalize: true,
        waveColor: cssVar("--wave", "#a5b4fc"),
        progressColor: cssVar("--wave-progress", "#4f46e5"),
        cursorColor: cssVar("--foreground", "#111"),
      });
      ws.current = instance;
      instance.on("ready", () => setReady(true));
      instance.on("play", () => setPlaying(true));
      instance.on("pause", () => setPlaying(false));
      instance.on("timeupdate", (t: number) => {
        setTime(t);
        onTimeRef.current?.(t);
      });
      if (peaks?.length) setReady(true);
    })();
    return () => {
      destroyed = true;
      instance?.destroy();
      ws.current = null;
    };
  }, [url, peaks, duration]);

  useImperativeHandle(ref, () => ({
    seek(seconds: number, autoplay = true) {
      const w = ws.current;
      if (!w) return;
      w.setTime(seconds);
      if (autoplay) void w.play();
    },
  }));

  return (
    <div className="rounded-xl border bg-card p-4">
      <div ref={container} aria-label="Audio waveform" className="min-h-[72px] w-full" />
      <div className="mt-3 flex items-center gap-3">
        <Button
          size="icon"
          onClick={() => void ws.current?.playPause()}
          disabled={!ready}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause /> : <Play />}
        </Button>
        <span className="font-mono text-sm tabular-nums text-muted-foreground" aria-live="off">
          {formatTimestamp(time)} / {formatTimestamp(duration ?? 0)}
        </span>
      </div>
    </div>
  );
});

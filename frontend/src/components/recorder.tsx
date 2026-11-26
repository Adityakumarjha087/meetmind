"use client";

import { Circle, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { formatTimestamp } from "@/lib/utils";

function pickMime(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((c) => MediaRecorder.isTypeSupported(c)) ?? "";
}

/** In-browser recording via MediaRecorder. Emits a File when the user stops. */
export function Recorder({ onRecorded }: { onRecorded: (file: File) => void }) {
  const [state, setState] = useState<"idle" | "recording" | "denied" | "unsupported">("idle");
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setState("unsupported");
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
      recorder.current?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const mime = pickMime();
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
        onRecorded(new File(chunks.current, `recording-${stamp}.${ext}`, { type }));
      };
      rec.start(1000);
      recorder.current = rec;
      setElapsed(0);
      timer.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      setState("recording");
    } catch {
      setState("denied");
    }
  }

  function stop() {
    recorder.current?.stop();
    if (timer.current) clearInterval(timer.current);
    setState("idle");
  }

  if (state === "unsupported") {
    return <p className="text-sm text-muted-foreground">Recording is not supported in this browser.</p>;
  }
  return (
    <div className="flex items-center gap-3">
      {state === "recording" ? (
        <Button type="button" variant="destructive" onClick={stop}>
          <Square /> Stop ({formatTimestamp(elapsed)})
        </Button>
      ) : (
        <Button type="button" variant="outline" onClick={start}>
          <Circle className="fill-destructive text-destructive" /> Record audio
        </Button>
      )}
      {state === "recording" && (
        <span className="flex items-center gap-1.5 text-sm text-destructive" aria-live="polite">
          <span className="size-2 animate-pulse rounded-full bg-destructive" /> Recording…
        </span>
      )}
      {state === "denied" && <p className="text-sm text-destructive">Microphone permission was denied.</p>}
    </div>
  );
}

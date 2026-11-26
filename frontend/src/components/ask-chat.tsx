"use client";

import { Quote, Send, Sparkles } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import type { Citation } from "@/lib/types";
import { formatTimestamp } from "@/lib/utils";

interface Turn {
  question: string;
  answer?: string;
  citations?: Citation[];
  error?: string;
}

const SUGGESTIONS = ["What did we decide about pricing?", "Who owns the press release?", "What are the open risks?"];

function citationHref(c: Citation) {
  return `/meetings/${c.meeting_id}?t=${Math.floor(c.start_s)}`;
}

/** Render "[2]" markers as links to the cited moment. */
export function AnswerText({ text, citations }: { text: string; citations: Citation[] }) {
  const byIndex = new Map(citations.map((c) => [c.index, c]));
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {parts.map((part, i) => {
        const m = /^\[(\d+)\]$/.exec(part);
        const c = m ? byIndex.get(Number(m[1])) : undefined;
        if (!c) return <Fragment key={i}>{part}</Fragment>;
        return (
          <Link
            key={i}
            href={citationHref(c)}
            className="mx-0.5 rounded bg-primary/12 px-1 align-super text-[0.7rem] font-semibold text-primary hover:underline"
            aria-label={`Source ${c.index}: ${c.meeting_title} at ${formatTimestamp(c.start_s)}`}
          >
            {c.index}
          </Link>
        );
      })}
    </p>
  );
}

export function AskChat({ workspaceId }: { workspaceId: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }), [turns]);

  async function ask(q: string) {
    const text = q.trim();
    if (text.length < 2 || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { question: text }]);
    try {
      const res = await api.ask(workspaceId, text);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer: res.answer, citations: res.citations } : turn)));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong";
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: message } : turn)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[60vh] flex-col rounded-xl border bg-card">
      <div className="flex-1 space-y-6 overflow-y-auto p-5" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-12 text-center">
            <Sparkles className="size-8 text-primary" aria-hidden />
            <div>
              <p className="font-medium">Ask anything about your past meetings</p>
              <p className="text-sm text-muted-foreground">Answers cite the exact moment they came from.</p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <Button key={s} variant="outline" size="sm" onClick={() => void ask(s)}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}
        {turns.map((turn, i) => (
          <div key={i} className="space-y-3">
            <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
              {turn.question}
            </div>
            {turn.error ? (
              <p role="alert" className="text-sm text-destructive">
                {turn.error}
              </p>
            ) : turn.answer === undefined ? (
              <p className="text-sm text-muted-foreground">Searching your meetings…</p>
            ) : (
              <div className="max-w-[90%] space-y-3 text-sm" data-testid="answer">
                <AnswerText text={turn.answer} citations={turn.citations ?? []} />
                {!!turn.citations?.length && (
                  <ul className="grid gap-2 sm:grid-cols-2" aria-label="Sources">
                    {turn.citations.map((c) => (
                      <li key={c.index}>
                        <Link href={citationHref(c)} className="block rounded-lg border p-3 text-xs transition-colors hover:bg-muted">
                          <span className="flex items-center gap-1.5 font-medium text-foreground">
                            <Quote className="size-3 text-primary" aria-hidden />[{c.index}] {c.meeting_title} · {formatTimestamp(c.start_s)}
                          </span>
                          <span className="mt-1 line-clamp-2 text-muted-foreground">{c.text}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor="ask-input" className="sr-only">
          Question
        </label>
        <Input id="ask-input" placeholder="Ask your meetings…" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} />
        <Button type="submit" disabled={busy || question.trim().length < 2} aria-label="Send question">
          <Send />
        </Button>
      </form>
    </div>
  );
}

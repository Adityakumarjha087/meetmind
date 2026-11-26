"""Deterministic, offline insight engine.

Rule-based extraction (commitments, requests, decisions, unresolved questions), lexicon sentiment
and TF-IDF extractive summarisation. It exists so the product is fully usable with zero API keys,
and doubles as a regression baseline for the LLM engines.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from app.intelligence.dates import resolve_due
from app.intelligence.text import (
    STOPWORDS,
    content_terms,
    jaccard,
    normalize_for_dedupe,
    split_sentences,
    words,
)
from app.intelligence.types import (
    AnalysisInput,
    AnalysisResult,
    AnswerResult,
    ContextChunk,
    LLMUsage,
    TranscriptLine,
    fmt_ts,
    render_transcript,
)
from app.llm.base import estimate_tokens
from app.schemas.insights import (
    ActionItemDraft,
    Decision,
    Insights,
    OpenQuestion,
    SpeakerSentiment,
)

POSITIVE = {
    "great", "good", "excited", "exciting", "fantastic", "awesome", "excellent", "love", "happy",
    "glad", "agree", "agreed", "perfect", "nice", "progress", "ready", "unblocks", "win", "success",
    "successful", "thanks", "thank", "appreciate", "confident", "smooth", "track", "improved", "solid",
}
NEGATIVE = {
    "worried", "worry", "concern", "concerned", "bug", "bugs", "issue", "issues", "problem",
    "problems", "risk", "risky", "blocked", "blocker", "delay", "delayed", "late", "frustrated",
    "frustrating", "bad", "fail", "failed", "failing", "broken", "unhappy", "difficult", "churn",
    "complaint", "complaints", "slow", "behind", "unclear", "confused", "crash", "crashes",
}
UNCERTAIN = re.compile(
    r"\b(not sure|don't know|do not know|no idea|unclear|tbd|to be determined|revisit|follow up on|"
    r"circle back|need to check|need to find out|open question)\b",
    re.I,
)

_COMMIT = re.compile(
    r"\b(?P<who>I|we)\s*(?:will|'ll|\s+am going to|'m going to|are going to|'re going to|can|shall)\s+"
    r"(?P<what>(?!be\b|do that\b|do it\b|do\b|try\b|see\b|think\b|have\b|help\b)[a-z].{6,})",
    re.I,
)
_REQUEST = re.compile(
    r"\b(?P<name>[A-Z][a-z]+)\s*,\s*(?:can you|could you|would you|please|will you)\s+(?P<what>.{6,})",
)
_NAMED_WILL = re.compile(
    r"\b(?P<name>[A-Z][a-z]+)\s+(?:will|is going to|is gonna)\s+(?P<what>(?!be\b)[a-z].{6,})"
)
_ACTION_TAG = re.compile(r"\baction item\s*[:\-]?\s*(?P<what>.{6,})", re.I)
_DECISION = re.compile(
    r"\b(we(?:'ve| have)? decided|decided to|we(?:'ve| have)? agreed|we agreed|agreed to|"
    r"the decision is|decision:|we(?:'re| are) going with|let's go with|we will go with|"
    r"final call|we'll go with|we settled on)\b",
    re.I,
)
_FILLER_PREFIX = re.compile(r"^(?:so|okay|ok|alright|well|and|also|great|good point)[,.]?\s+", re.I)
_TRAILING = re.compile(r"[\s,;:.!?]+$")
_NON_NAMES = {"I", "We", "You", "So", "And", "But", "Okay", "Ok", "Yes", "No", "Please", "Also", "Then", "Thanks", "Great", "Good", "Well"}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


@dataclass(frozen=True)
class Sentence:
    text: str
    speaker: str
    start: float


def _sentences(lines: list[TranscriptLine]) -> list[Sentence]:
    out: list[Sentence] = []
    for ln in lines:
        for s in split_sentences(ln.text):
            out.append(Sentence(s, ln.speaker, ln.start))
    return out


def _clean_title(what: str, due_span: tuple[int, int] | None) -> str:
    if due_span:
        what = (what[: due_span[0]] + what[due_span[1] :]).strip()
    what = re.sub(r"\s+", " ", what)
    what = _TRAILING.sub("", what)
    what = re.sub(r"\b(for me|for us|please)\b", "", what, flags=re.I).strip()
    what = _TRAILING.sub("", what)
    return what[:1].upper() + what[1:] if what else what


class HeuristicEngine:
    name = "offline"

    # ------------------------------------------------------------------ extraction
    def _action_items(self, data: AnalysisInput, sents: list[Sentence]) -> list[ActionItemDraft]:
        items: list[ActionItemDraft] = []
        for s in sents:
            owner: str | None = None
            what: str | None = None
            if m := _REQUEST.search(s.text):
                if m.group("name") not in _NON_NAMES:
                    owner, what = m.group("name"), m.group("what")
            if what is None and (m := _ACTION_TAG.search(s.text)):
                what = m.group("what")
            if what is None and (m := _NAMED_WILL.search(s.text)):
                if m.group("name") not in _NON_NAMES:
                    owner, what = m.group("name"), m.group("what")
            if what is None and (m := _COMMIT.search(s.text)):
                if s.text.rstrip().endswith("?"):
                    continue
                what = m.group("what")
                owner = s.speaker if m.group("who").lower() == "i" else None
            if not what:
                continue
            due, due_text, span = resolve_due(what, data.meeting_date)
            title = _clean_title(what, span)
            if len(words(title)) < 2:
                continue
            items.append(
                ActionItemDraft(
                    title=title,
                    owner=owner,
                    due_date=due,
                    due_text=due_text,
                    timestamp_s=round(s.start, 2),
                )
            )
        return _dedupe(items, key=lambda a: a.title)

    def _decisions(self, sents: list[Sentence]) -> list[Decision]:
        out: list[Decision] = []
        for s in sents:
            m = _DECISION.search(s.text)
            if not m:
                continue
            tail = s.text[m.end() :]
            if len(words(tail)) < 3:
                continue
            text = _FILLER_PREFIX.sub("", s.text).strip()
            text = text[:1].upper() + text[1:]
            out.append(Decision(text=_TRAILING.sub("", text) + ".", timestamp_s=round(s.start, 2)))
        return _dedupe(out, key=lambda d: d.text)

    def _open_questions(self, sents: list[Sentence]) -> list[OpenQuestion]:
        out: list[OpenQuestion] = []
        for i, s in enumerate(sents):
            text = s.text.strip()
            explicit = re.search(r"\bopen question\b", text, re.I)
            if not (text.endswith("?") or explicit):
                continue
            if _REQUEST.search(text) or re.match(r"^(can|could|would) you\b", text, re.I):
                continue  # a request, captured as an action item
            follow = sents[i + 1 : i + 3]
            answered_by_other = [f for f in follow if f.speaker != s.speaker]
            unresolved = any(UNCERTAIN.search(f.text) for f in follow)
            if explicit or unresolved or not answered_by_other:
                q = _FILLER_PREFIX.sub("", re.sub(r"^one concern[.:,]?\s*", "", text, flags=re.I))
                out.append(OpenQuestion(text=q[:1].upper() + q[1:], timestamp_s=round(s.start, 2)))
        return _dedupe(out, key=lambda q: q.text)

    def _sentiment(self, lines: list[TranscriptLine]) -> list[SpeakerSentiment]:
        pos: Counter[str] = Counter()
        neg: Counter[str] = Counter()
        talk: defaultdict[str, float] = defaultdict(float)
        wc: Counter[str] = Counter()
        for ln in lines:
            toks = words(ln.text)
            talk[ln.speaker] += max(0.0, ln.end - ln.start)
            wc[ln.speaker] += len(toks)
            for i, t in enumerate(toks):
                negated = i > 0 and toks[i - 1] in {"not", "no", "never", "isn't", "don't", "aren't"}
                if t in POSITIVE:
                    (neg if negated else pos)[ln.speaker] += 1
                elif t in NEGATIVE:
                    (pos if negated else neg)[ln.speaker] += 1
        out: list[SpeakerSentiment] = []
        for speaker in sorted(talk, key=lambda sp: -talk[sp]):
            p, n = pos[speaker], neg[speaker]
            score = round((p - n) / (p + n + 2), 3)
            label = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
            out.append(
                SpeakerSentiment(
                    speaker=speaker,
                    score=max(-1.0, min(1.0, score)),
                    label=label,
                    rationale=f"{p} positive vs {n} negative cue words",
                    talk_time_s=round(talk[speaker], 2),
                    word_count=wc[speaker],
                )
            )
        return out

    def _topics(self, sents: list[Sentence], k: int = 6) -> list[str]:
        uni: Counter[str] = Counter()
        bi: Counter[str] = Counter()
        for s in sents:
            toks = [t for t in words(s.text) if t not in STOPWORDS and len(t) > 2 and not t.isdigit()]
            uni.update(toks)
            raw = words(s.text)
            for a, b in zip(raw, raw[1:], strict=False):
                if a not in STOPWORDS and b not in STOPWORDS and len(a) > 2 and len(b) > 2:
                    bi[f"{a} {b}"] += 1
        topics = [p for p, c in bi.most_common(k) if c >= 2]
        for w, _ in uni.most_common(k * 2):
            if len(topics) >= k:
                break
            if not any(w in t for t in topics):
                topics.append(w)
        return topics[:k]

    def _summary_sentences(self, sents: list[Sentence], k: int = 3) -> list[Sentence]:
        if not sents:
            return []
        docs = [set(content_terms(s.text)) for s in sents]
        df: Counter[str] = Counter(t for d in docs for t in d)
        n = len(docs)
        tf: Counter[str] = Counter(t for s in sents for t in content_terms(s.text))
        scores = []
        for i, (s, d) in enumerate(zip(sents, docs, strict=True)):
            if len(words(s.text)) < 6 or s.text.endswith("?"):
                scores.append(0.0)
                continue
            weight = sum(tf[t] * math.log(1 + n / df[t]) for t in d) / math.sqrt(len(d) + 1)
            if _DECISION.search(s.text):
                weight *= 1.5
            if i < max(3, n // 10):
                weight *= 1.2  # openings tend to state the agenda
            scores.append(weight)
        top = sorted(range(n), key=lambda i: -scores[i])[:k]
        return [sents[i] for i in sorted(top) if scores[i] > 0]

    # ------------------------------------------------------------------ engine API
    def analyze(self, data: AnalysisInput) -> AnalysisResult:
        sents = _sentences(data.lines)
        actions = self._action_items(data, sents)
        decisions = self._decisions(sents)
        questions = self._open_questions(sents)
        sentiment = self._sentiment(data.lines)
        topics = self._topics(sents)
        key = self._summary_sentences(sents, k=4)
        summary = self._compose_summary(data, sentiment, topics, decisions, actions, questions, key)
        insights = Insights(
            executive_summary=summary,
            key_points=[_cap(_TRAILING.sub("", _FILLER_PREFIX.sub("", s.text))) + "." for s in key],
            decisions=decisions,
            action_items=actions,
            open_questions=questions,
            sentiment=sentiment,
            topics=topics,
            engine=self.name,
        )
        return AnalysisResult(insights, [self._usage(render_transcript(data.lines), insights)])

    def _compose_summary(
        self,
        data: AnalysisInput,
        sentiment: list[SpeakerSentiment],
        topics: list[str],
        decisions: list[Decision],
        actions: list[ActionItemDraft],
        questions: list[OpenQuestion],
        key: list[Sentence],
    ) -> str:
        if not data.lines:
            return "No speech was detected in this recording."
        mins = max(1, round(data.duration_s / 60))
        parts = [
            f"{len(sentiment)} participant{'s' if len(sentiment) != 1 else ''} met for about "
            f"{mins} minute{'s' if mins != 1 else ''}"
            + (f" to discuss {', '.join(topics[:3])}." if topics else ".")
        ]
        if key:
            parts.append(_cap(_TRAILING.sub("", _FILLER_PREFIX.sub("", key[0].text))) + ".")
        if decisions:
            parts.append(
                f"{len(decisions)} decision{'s were' if len(decisions) != 1 else ' was'} made, "
                f"including: {decisions[0].text.rstrip('.')}."
            )
        if actions:
            owners = sorted({a.owner for a in actions if a.owner})
            parts.append(
                f"{len(actions)} action item{'s were' if len(actions) != 1 else ' was'} assigned"
                + (f" to {', '.join(owners)}." if owners else ".")
            )
        if questions:
            parts.append(f"{len(questions)} question{'s remain' if len(questions) != 1 else ' remains'} open.")
        return " ".join(parts)

    def reduce(self, data: AnalysisInput, partials: list[Insights]) -> AnalysisResult:
        decisions = _dedupe([d for p in partials for d in p.decisions], key=lambda d: d.text)
        actions = _dedupe([a for p in partials for a in p.action_items], key=lambda a: a.title)
        questions = _dedupe([q for p in partials for q in p.open_questions], key=lambda q: q.text)
        sents = _sentences(data.lines)
        sentiment = self._sentiment(data.lines)
        topic_counts: Counter[str] = Counter(t for p in partials for t in p.topics)
        topics = [t for t, _ in topic_counts.most_common(6)]
        key_points = []
        for p in partials:
            key_points.extend(p.key_points[:2])
        key = self._summary_sentences(sents, k=1)
        summary = self._compose_summary(data, sentiment, topics, decisions, actions, questions, key)
        insights = Insights(
            executive_summary=summary,
            key_points=key_points[:8],
            decisions=decisions,
            action_items=actions,
            open_questions=questions,
            sentiment=sentiment,
            topics=topics,
            strategy="map_reduce",
            chunks_processed=len(partials),
            engine=self.name,
        )
        prompt = "\n".join(p.model_dump_json() for p in partials)
        return AnalysisResult(insights, [self._usage(prompt, insights)])

    def answer(self, question: str, contexts: list[ContextChunk]) -> AnswerResult:
        q_terms = set(content_terms(question))
        scored: list[tuple[float, ContextChunk, str]] = []
        for ctx in contexts:
            for sent in split_sentences(ctx.text):
                terms = set(content_terms(sent))
                overlap = len(q_terms & terms)
                if overlap:
                    scored.append((overlap / math.sqrt(len(terms) + 1) + 0.1 * ctx.score, ctx, sent))
        if not scored:
            return AnswerResult(
                "I couldn't find anything about that in your meetings.",
                [],
                [LLMUsage("offline", "heuristic", estimate_tokens(question), 12, 0.0, True)],
            )
        scored.sort(key=lambda t: -t[0])
        picked: list[tuple[ContextChunk, str]] = []
        seen: set[str] = set()
        for _, ctx, sent in scored:
            if sent not in seen:
                picked.append((ctx, sent))
                seen.add(sent)
            if len(picked) == 3:
                break
        lines = [
            f"- In \"{ctx.meeting_title}\" at {fmt_ts(ctx.start_s)}: {sent} [{ctx.index}]"
            for ctx, sent in picked
        ]
        answer = "Here is what your meetings say:\n" + "\n".join(lines)
        cited = sorted({ctx.index for ctx, _ in picked})
        prompt_tokens = estimate_tokens(question + "".join(c.text for c in contexts))
        return AnswerResult(
            answer, cited, [LLMUsage("offline", "heuristic", prompt_tokens, estimate_tokens(answer), 0.0, True)]
        )

    @staticmethod
    def _usage(prompt: str, insights: Insights) -> LLMUsage:
        return LLMUsage(
            provider="offline",
            model="heuristic",
            input_tokens=estimate_tokens(prompt) + 400,  # + system prompt the LLM path would send
            output_tokens=estimate_tokens(insights.model_dump_json()),
            latency_ms=0.0,
            estimated=True,
        )


def _dedupe[T](items: list[T], key: Callable[[T], str]) -> list[T]:
    out: list[T] = []
    sigs: list[frozenset[str]] = []
    for item in items:
        sig = normalize_for_dedupe(key(item))
        if any(jaccard(sig, s) >= 0.7 for s in sigs):
            continue
        sigs.append(sig)
        out.append(item)
    return out

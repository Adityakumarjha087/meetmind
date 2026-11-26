"""Markdown and PDF exports of a meeting's notes."""

from __future__ import annotations

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.intelligence.types import fmt_ts
from app.models import ActionItem, Meeting
from app.services.pipeline import insights_of


def to_markdown(meeting: Meeting, items: list[ActionItem], include_transcript: bool = True) -> str:
    insights = insights_of(meeting)
    when = (meeting.scheduled_at or meeting.created_at).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"# {meeting.title}", "", f"*{when} · {fmt_ts(meeting.duration_s or 0)}*", ""]
    if insights:
        out += ["## Executive summary", "", insights.executive_summary, ""]
        if insights.key_points:
            out += ["## Key points", "", *[f"- {p}" for p in insights.key_points], ""]
        if insights.decisions:
            out += ["## Decisions", ""]
            out += [f"- {d.text}" + (f" _({fmt_ts(d.timestamp_s)})_" if d.timestamp_s is not None else "") for d in insights.decisions]
            out.append("")
    if items:
        out += ["## Action items", "", "| Status | Task | Owner | Due |", "|---|---|---|---|"]
        for it in items:
            box = "x" if it.status.value == "done" else " "
            due = it.due_date.isoformat() if it.due_date else "—"
            out.append(f"| [{box}] | {it.title} | {it.owner_name or '—'} | {due} |")
        out.append("")
    if insights and insights.open_questions:
        out += ["## Open questions", "", *[f"- {q.text}" for q in insights.open_questions], ""]
    if insights and insights.sentiment:
        out += ["## Speakers", "", "| Speaker | Talk time | Sentiment |", "|---|---|---|"]
        for s in insights.sentiment:
            out.append(f"| {s.speaker} | {fmt_ts(s.talk_time_s)} | {s.label} ({s.score:+.2f}) |")
        out.append("")
    if include_transcript and meeting.segments:
        out += ["## Transcript", ""]
        for seg in meeting.segments:
            name = seg.speaker.display_name if seg.speaker else "Unknown"
            out.append(f"**[{fmt_ts(seg.start_s)}] {name}:** {seg.text}  ")
        out.append("")
    return "\n".join(out)


def _latin1(text: str) -> str:
    replacements = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "•": "-", "…": "..."}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(130)
        self.cell(0, 8, f"MeetMind - page {self.page_no()}", align="C")


def to_pdf(meeting: Meeting, items: list[ActionItem]) -> bytes:
    insights = insights_of(meeting)
    pdf = _PDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 9, _latin1(meeting.title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(110)
    when = (meeting.scheduled_at or meeting.created_at).strftime("%Y-%m-%d %H:%M UTC")
    pdf.cell(0, 6, _latin1(f"{when}  |  duration {fmt_ts(meeting.duration_s or 0)}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0)

    def heading(text: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", size=10)

    def bullet(text: str) -> None:
        pdf.multi_cell(0, 5.5, _latin1(f"-  {text}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if insights:
        heading("Executive summary")
        pdf.multi_cell(0, 5.5, _latin1(insights.executive_summary), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if insights.decisions:
            heading("Decisions")
            for d in insights.decisions:
                bullet(d.text)
    if items:
        heading("Action items")
        for it in items:
            meta = ", ".join(x for x in [it.owner_name or "", f"due {it.due_date.isoformat()}" if it.due_date else "", it.status.value.replace("_", " ")] if x)
            bullet(f"{it.title} ({meta})")
    if insights and insights.open_questions:
        heading("Open questions")
        for q in insights.open_questions:
            bullet(q.text)
    if meeting.segments:
        heading("Transcript")
        pdf.set_font("Helvetica", size=9)
        for seg in meeting.segments:
            name = seg.speaker.display_name if seg.speaker else "Unknown"
            pdf.multi_cell(0, 5, _latin1(f"[{fmt_ts(seg.start_s)}] {name}: {seg.text}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())

"""Resolve natural-language due dates ("by next Friday", "end of the month") relative to a meeting."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "twenty-first": 21, "twenty first": 21,
    "twenty-second": 22, "twenty second": 22, "twenty-third": 23, "twenty third": 23,
    "twenty-fourth": 24, "twenty fourth": 24, "twenty-fifth": 25, "twenty fifth": 25,
    "thirtieth": 30, "thirty-first": 31, "thirty first": 31,
}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a": 1, "an": 1}

_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?|(?P<oday>" + "|".join(
    sorted(map(re.escape, ORDINALS), key=len, reverse=True)
) + ")"
_MONTH = "(?P<month>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("eom", re.compile(r"\b(?:by |before |until )?(?:the )?end of (?:the |this )?month\b", re.I)),
    ("eow", re.compile(r"\b(?:by |before |until )?(?:the )?end of (?:the |this )?week\b", re.I)),
    ("eod", re.compile(r"\b(?:by |before )?(?:the )?end of (?:the )?day\b", re.I)),
    ("tomorrow", re.compile(r"\b(?:by |before |until )?tomorrow\b", re.I)),
    ("today", re.compile(r"\b(?:by |before )?(?:today|tonight)\b", re.I)),
    ("next_week", re.compile(r"\b(?:by |before |until )?next week\b", re.I)),
    ("in_n", re.compile(r"\b(?:with)?in (?P<n>\d+|one|two|three|four|five|six|a|an) (?P<unit>days?|weeks?)\b", re.I)),
    ("weekday", re.compile(r"\b(?:by |before |until |on |this )?(?P<next>next )?(?P<wd>" + "|".join(WEEKDAYS) + r")\b", re.I)),
    ("month_day", re.compile(r"\b(?:by |before |until |on )?" + _MONTH + r"\s+(?:the\s+)?(?:" + _DAY + r")\b", re.I)),
    ("day_month", re.compile(r"\b(?:by |before |until |on )?(?:the\s+)?(?:" + _DAY + r")\s+(?:of\s+)?" + _MONTH, re.I)),
]


def _upcoming_weekday(base: date, weekday: int, strictly_next_week: bool) -> date:
    delta = (weekday - base.weekday()) % 7 or 7
    candidate = base + timedelta(days=delta)
    if strictly_next_week:
        start_next_week = base + timedelta(days=7 - base.weekday())
        if candidate < start_next_week:
            candidate += timedelta(days=7)
    return candidate


def _day_of(match: re.Match[str]) -> int | None:
    if match.groupdict().get("day"):
        return int(match.group("day"))
    if match.groupdict().get("oday"):
        return ORDINALS[match.group("oday").lower()]
    return None


def resolve_due(text: str, base: date) -> tuple[date | None, str | None, tuple[int, int] | None]:
    """Return (due_date, matched_phrase, span) for the first recognised due phrase in ``text``."""
    best: tuple[int, str, re.Match[str]] | None = None
    for kind, pattern in PATTERNS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), kind, m)
    if best is None:
        return None, None, None
    _, kind, m = best
    due: date | None
    if kind == "eom":
        due = base.replace(day=calendar.monthrange(base.year, base.month)[1])
    elif kind == "eow":
        due = base + timedelta(days=(4 - base.weekday()) % 7)
    elif kind in {"eod", "today"}:
        due = base
    elif kind == "tomorrow":
        due = base + timedelta(days=1)
    elif kind == "next_week":
        due = base + timedelta(days=7 - base.weekday())
    elif kind == "in_n":
        raw = m.group("n").lower()
        n = int(raw) if raw.isdigit() else NUMBERS[raw]
        due = base + timedelta(days=n * (7 if m.group("unit").lower().startswith("week") else 1))
    elif kind == "weekday":
        due = _upcoming_weekday(base, WEEKDAYS.index(m.group("wd").lower()), bool(m.group("next")))
    else:
        month = MONTHS[m.group("month").lower().rstrip(".")]
        day = _day_of(m)
        due = None
        if day is not None:
            year = base.year
            try:
                due = date(year, month, day)
                if due < base - timedelta(days=30):
                    due = date(year + 1, month, day)
            except ValueError:
                due = None
    return due, m.group(0).strip(), m.span()

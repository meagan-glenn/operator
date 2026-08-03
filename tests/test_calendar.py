"""Tests for calendar slot generation and ICS escaping (pure logic, no Google)."""
import asyncio
import re
from datetime import datetime

from second_me.tools import calendar as cal

AVAILABILITY = {
    "timezone": "America/Los_Angeles",
    "working_hours": {"start": "09:00", "end": "12:00"},
    "default_call_minutes": 30,
    "buffer_minutes": 15,
    "no_meeting_days": [],
    "protected_blocks": [],
    "google": {},
}


def _suggest(monkeypatch, availability, **args):
    monkeypatch.setattr(cal, "load_availability", lambda: availability)
    monkeypatch.setattr(cal, "google_connected", lambda: False)
    result = asyncio.run(cal.suggest_call_slots.handler(args))
    return result["content"][0]["text"]


def _starts(text) -> list[datetime]:
    return [datetime.strptime(m, "%Y-%m-%d %H:%M") for m in re.findall(r"\[start=([\d: -]+)\]", text)]


def test_slots_respect_working_hours(monkeypatch):
    text = _suggest(monkeypatch, AVAILABILITY, days_ahead=7, count=4, duration_min=30)
    starts = _starts(text)
    assert starts, text
    for s in starts:
        assert s.hour >= 9
        # Slot must END by 12:00.
        assert (s.hour, s.minute) <= (11, 30)


def test_slots_skip_no_meeting_days(monkeypatch):
    av = dict(AVAILABILITY)
    av["no_meeting_days"] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    text = _suggest(monkeypatch, av, days_ahead=7, count=3)
    assert "No open slots" in text


def test_slots_jump_protected_blocks(monkeypatch):
    av = dict(AVAILABILITY)
    av["protected_blocks"] = [
        {
            "label": "Deep work",
            "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "start": "09:00",
            "end": "10:30",
        }
    ]
    text = _suggest(monkeypatch, av, days_ahead=7, count=4, duration_min=30)
    for s in _starts(text):
        assert (s.hour, s.minute) >= (10, 30)


def test_slots_apply_buffer_between_same_day_slots(monkeypatch):
    text = _suggest(monkeypatch, AVAILABILITY, days_ahead=2, count=2, duration_min=30)
    starts = _starts(text)
    assert len(starts) == 2
    if starts[0].date() == starts[1].date():
        # second slot = first end (30min) + buffer (15min)
        delta = (starts[1] - starts[0]).total_seconds() / 60
        assert delta == 45


def test_not_busy_checked_note_when_google_off(monkeypatch):
    text = _suggest(monkeypatch, AVAILABILITY, days_ahead=5, count=1)
    assert "NOT busy-checked" in text


def test_ics_escape():
    assert cal._ics_escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    assert cal._ics_escape("plain") == "plain"

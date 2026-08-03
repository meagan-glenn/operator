"""Calendar tools: propose call times and create real calendar events.

When Google Calendar is connected, suggest_call_slots checks your REAL busy
times across all your calendars, and create_event books directly onto Google
(into your primary calendar by default). When Google isn't connected, it falls
back gracefully: slots come from your availability rules only, and create_event
writes a standards-compliant .ics file you can open or attach.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from claude_agent_sdk import tool

from ..config import CALENDAR_DIR, EVENTS_FILE, ensure_dirs, load_availability
from ..google_auth import is_connected as google_connected
from . import gcal
from ._common import _err, _ok, _slug, load_json_store, save_json_store

EVENT_KINDS = ["call", "deep_work", "fun", "personal"]
_ET = ZoneInfo("America/New_York")  # most founders are East Coast — always show ET too


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _fmt(dt: datetime) -> str:
    # e.g. "9:30am". %-I (no-leading-zero hour) is POSIX/macOS-specific strftime —
    # it would break on Windows (%#I there), which is fine for this Mac-local agent.
    return dt.strftime("%-I:%M%p").lower()


def _both_zones(start: datetime, end: datetime) -> str:
    s_et, e_et = start.astimezone(_ET), end.astimezone(_ET)
    return f"{_fmt(start)}–{_fmt(end)} PT ({_fmt(s_et)}–{_fmt(e_et)} ET)"


def _parse_local(s: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(s.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _build_ics(uid: str, title: str, start: datetime, end: datetime, notes: str, attendee: str, kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtend = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    desc = " ".join(filter(None, [notes, f"(kind: {kind})"]))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//second-me//operator//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}@second-me",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_ics_escape(title)}",
        f"DESCRIPTION:{_ics_escape(desc)}",
    ]
    if attendee:
        lines.append(f"ATTENDEE;RSVP=TRUE:mailto:{attendee}")
    lines += ["STATUS:CONFIRMED", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _load_events() -> list:
    return load_json_store(EVENTS_FILE, [])


def _save_events(events: list) -> None:
    ensure_dirs()
    save_json_store(EVENTS_FILE, events)


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------
def _overlaps_busy(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    s, e = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    return any(s < be and e > bs for bs, be in busy)


async def _gather_busy(now: datetime, days_ahead: int) -> tuple[list[tuple[datetime, datetime]], bool]:
    """Return (busy_intervals, connected). Empty + False when Google isn't connected.

    Busy times are gathered across every calendar of every connected account.
    """
    if not google_connected():
        return [], False
    exclude = load_availability().get("google", {}).get("exclude_calendars", [])
    busy = await gcal.get_busy_all(now, now + timedelta(days=days_ahead + 1), exclude)
    return busy, True


@tool(
    "suggest_call_slots",
    "Propose open call times respecting working hours, buffers, and protected blocks. When Google Calendar is "
    "connected, slots are filtered against real busy times across all your calendars. Returns times in both PT and ET.",
    {"days_ahead": int, "count": int, "duration_min": int},
)
async def suggest_call_slots(args: dict) -> dict:
    av = load_availability()
    tz = ZoneInfo(av["timezone"])
    days_ahead = int(args.get("days_ahead") or 5)
    count = int(args.get("count") or 3)
    duration = int(args.get("duration_min") or av.get("default_call_minutes", 30))
    buffer = int(av.get("buffer_minutes", 0))
    no_days = set(av.get("no_meeting_days", []))
    blocks = av.get("protected_blocks", [])
    wh_start, wh_end = _hhmm(av["working_hours"]["start"]), _hhmm(av["working_hours"]["end"])

    now = datetime.now(tz)
    busy, connected = await _gather_busy(now, days_ahead)

    slots: list[datetime] = []
    for offset in range(1, days_ahead + 1):
        if len(slots) >= count:
            break
        day = (now + timedelta(days=offset)).date()
        weekday = day.strftime("%A")
        if weekday in no_days:
            continue
        day_blocks = [b for b in blocks if weekday in b.get("days", [])]
        cursor = datetime(day.year, day.month, day.day, wh_start[0], wh_start[1], tzinfo=tz)
        end_limit = datetime(day.year, day.month, day.day, wh_end[0], wh_end[1], tzinfo=tz)
        per_day = 0
        while cursor + timedelta(minutes=duration) <= end_limit and per_day < 2 and len(slots) < count:
            slot_end = cursor + timedelta(minutes=duration)
            blocked = False
            for b in day_blocks:
                bs, be = _hhmm(b["start"]), _hhmm(b["end"])
                b_start = datetime(day.year, day.month, day.day, bs[0], bs[1], tzinfo=tz)
                b_end = datetime(day.year, day.month, day.day, be[0], be[1], tzinfo=tz)
                if cursor < b_end and slot_end > b_start:
                    cursor = b_end  # jump past the protected block
                    blocked = True
                    break
            if blocked:
                continue
            if _overlaps_busy(cursor, slot_end, busy):
                cursor = slot_end  # busy on a real calendar — try the next slot
                continue
            slots.append(cursor)
            per_day += 1
            cursor = slot_end + timedelta(minutes=buffer)

    if not slots:
        return _ok("No open slots found in the window. Try a larger days_ahead, or check availability.json.")

    lines = []
    for i, s in enumerate(slots, 1):
        e = s + timedelta(minutes=duration)
        lines.append(f"{i}. {s.strftime('%A %b %-d')} — {_both_zones(s, e)}  [start={s.strftime('%Y-%m-%d %H:%M')}]")
    if connected:
        note = (
            f"{len(slots)} open {duration}-min slot(s), checked against your real Google Calendar busy times. "
            "Use the [start=...] value with create_event to book."
        )
    else:
        note = (
            f"{len(slots)} proposed {duration}-min slot(s) from your availability rules. Google Calendar isn't "
            "connected, so these are NOT busy-checked — confirm before sending. Use [start=...] with create_event."
        )
    return _ok(note + "\n" + "\n".join(lines))


@tool(
    "create_event",
    "Create a calendar event. When Google Calendar is connected this books directly onto Google "
    "(the account/calendar configured in availability.json google.default_booking_account by default; "
    "pass account and/or calendar_id to override) and emails the attendee if given. Otherwise it writes a "
    ".ics invite file. start must be 'YYYY-MM-DD HH:MM' in Pacific time. kind: call, deep_work, fun, personal.",
    {"title": str, "start": str, "duration_min": int, "kind": str, "attendee_email": str, "notes": str, "calendar_id": str, "account": str},
)
async def create_event(args: dict) -> dict:
    ensure_dirs()
    av = load_availability()
    tz = ZoneInfo(av["timezone"])
    title = (args.get("title") or "Untitled").strip()
    kind = (args.get("kind") or "call").strip().lower()
    if kind not in EVENT_KINDS:
        return _err(f"Invalid kind '{kind}'. Use one of: {', '.join(EVENT_KINDS)}.")
    duration = int(args.get("duration_min") or av.get("default_call_minutes", 30))
    try:
        start = _parse_local(args.get("start") or "", tz)
    except ValueError:
        return _err("Couldn't parse start. Use 'YYYY-MM-DD HH:MM' in Pacific time, e.g. '2026-06-09 09:30'.")
    end = start + timedelta(minutes=duration)
    attendee = (args.get("attendee_email") or "").strip()
    notes = (args.get("notes") or "").strip()
    when = f"{start.strftime('%a %b %-d')} {_both_zones(start, end)}, {duration}min"

    # Two-way path: book directly onto Google Calendar.
    if google_connected():
        google_cfg = av.get("google", {})
        account = (args.get("account") or google_cfg.get("default_booking_account") or "").strip() or None
        target = (args.get("calendar_id") or google_cfg.get("default_booking_calendar") or "primary").strip()
        desc = " ".join(filter(None, [notes, f"(kind: {kind})"]))
        try:
            res = await gcal.insert_event(target, title, start, end, av["timezone"], desc, attendee, account=account)
        except Exception as e:
            return _err(f"Google booking failed: {e}. Fix the connection or omit account/calendar_id.")
        events = _load_events()
        events.append({
            "id": (res.get("id") or uuid.uuid4().hex)[:8],
            "title": title, "kind": kind, "start_pt": start.strftime("%Y-%m-%d %H:%M"),
            "duration_min": duration, "attendee": attendee,
            "account": account or "", "calendar_id": target,
            "google_link": res.get("link", ""), "created_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_events(events)
        where = f"{account} / {target}" if account else target
        msg = f"Booked {kind} on Google Calendar ({where}): '{title}' — {when}."
        if attendee:
            msg += f"\nInvite emailed to {attendee}."
        if res.get("link"):
            msg += f"\n{res['link']}"
        return _ok(msg)

    # Fallback path: write a .ics file (Google not connected).
    uid = uuid.uuid4().hex
    ics = _build_ics(uid, title, start, end, notes, attendee, kind)
    slug = _slug(title, 40)
    path = CALENDAR_DIR / f"{start.strftime('%Y%m%d-%H%M')}-{kind}-{slug}.ics"
    path.write_text(ics, encoding="utf-8")

    events = _load_events()
    events.append({
        "id": uid[:8], "title": title, "kind": kind, "start_pt": start.strftime("%Y-%m-%d %H:%M"),
        "duration_min": duration, "attendee": attendee, "ics": str(path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_events(events)
    return _ok(
        f"Created {kind}: '{title}' — {when}.\nInvite: {path}\n"
        "Double-click the .ics to add it to your calendar, or attach it to the booking email. "
        "(Connect Google Calendar to book automatically — see SETUP_GOOGLE.md.)"
    )


@tool(
    "list_events",
    "List calendar events Operator has created, newest first.",
    {"limit": int},
)
async def list_events(args: dict) -> dict:
    events = list(reversed(_load_events()))
    limit = int(args.get("limit") or 20)
    events = events[:limit]
    if not events:
        return _ok("No events created yet. Use create_event (often after suggest_call_slots).")
    lines = [
        f"[{e['id']}] {e['kind']}: {e['title']} — {e['start_pt']} PT ({e['duration_min']}min)"
        + (f" w/ {e['attendee']}" if e.get("attendee") else "")
        for e in events
    ]
    return _ok(f"{len(events)} event(s), newest first:\n" + "\n".join(lines))


CALENDAR_TOOLS = [suggest_call_slots, create_event, list_events]

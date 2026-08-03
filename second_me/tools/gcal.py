"""Google Calendar tools + internal helpers (multi-account).

Internal async helpers (list_calendars_raw, get_busy_all, insert_event) are used
by the scheduling logic in calendar.py. The @tool functions expose calendar
reading directly to the agent. All Google calls run in a thread so they don't
block the event loop, and everything degrades gracefully when Google isn't
connected.

The agent can hold several Google accounts at once. Conflict-checking spans every
calendar of every connected account; booking targets a single account chosen in
availability.json (google.default_booking_account).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from claude_agent_sdk import tool

from ..google_auth import get_service, get_services, is_connected, list_accounts
from ._common import _err, _ok


def parse_rfc3339(s: str) -> datetime:
    """Parse a Google timestamp (may end in 'Z') into an aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ----------------------------------------------------------------------------
# Internal helpers (used by calendar.py)
# ----------------------------------------------------------------------------
async def list_calendars_raw() -> list | None:
    """All calendars across all connected accounts, or None if not connected.

    Each entry is tagged with the account (email) it belongs to.
    """
    services = await asyncio.to_thread(get_services)
    if not services:
        return None

    def _do():
        out = []
        for email, service in services.items():
            try:
                items = service.calendarList().list().execute().get("items", [])
            except Exception:
                continue
            for c in items:
                out.append(
                    {
                        "id": c["id"],
                        "summary": c.get("summary", ""),
                        "primary": bool(c.get("primary", False)),
                        "access": c.get("accessRole", ""),
                        "account": email,
                    }
                )
        return out

    return await asyncio.to_thread(_do)


async def get_busy_all(
    start: datetime, end: datetime, exclude: list[str] | None = None
) -> list[tuple[datetime, datetime]]:
    """Busy intervals across every calendar of every connected account.

    freebusy can only query calendars an account can see, so we query once per
    account using that account's own calendar list, then aggregate. Calendars
    whose id or name is in `exclude` are skipped (e.g. holidays, personal).
    """
    services = await asyncio.to_thread(get_services)
    if not services:
        return []
    skip = {e.strip().lower() for e in (exclude or [])}

    def _do():
        out: list[tuple[datetime, datetime]] = []
        time_min = start.astimezone(timezone.utc).isoformat()
        time_max = end.astimezone(timezone.utc).isoformat()
        for service in services.values():
            try:
                items = service.calendarList().list().execute().get("items", [])
            except Exception:
                continue
            cal_ids = [
                c["id"]
                for c in items
                if c["id"].lower() not in skip and c.get("summary", "").lower() not in skip
            ]
            if not cal_ids:
                continue
            body = {
                "timeMin": time_min,
                "timeMax": time_max,
                "items": [{"id": cid} for cid in cal_ids],
            }
            try:
                resp = service.freebusy().query(body=body).execute()
            except Exception:
                continue
            for cal in resp.get("calendars", {}).values():
                for b in cal.get("busy", []):
                    out.append((parse_rfc3339(b["start"]), parse_rfc3339(b["end"])))
        return out

    return await asyncio.to_thread(_do)


async def insert_event(
    calendar_id: str,
    summary: str,
    start: datetime,
    end: datetime,
    timezone_name: str,
    description: str = "",
    attendee_email: str = "",
    account: str | None = None,
) -> dict:
    """Create a real event on Google Calendar. Returns {id, link}.

    `account` selects which connected account's calendar to write to. If omitted,
    we resolve the account that owns `calendar_id`; if that can't be determined
    (e.g. calendar_id == "primary"), we fall back to the first connected account.
    """
    if account is None and calendar_id != "primary":
        cals = await list_calendars_raw()
        for c in cals or []:
            if c["id"] == calendar_id:
                account = c["account"]
                break

    service = await asyncio.to_thread(get_service, account)
    if service is None:
        raise RuntimeError("Google Calendar is not connected.")

    def _do():
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        }
        send_updates = "none"
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]
            send_updates = "all"
        created = service.events().insert(
            calendarId=calendar_id, body=body, sendUpdates=send_updates
        ).execute()
        return {"id": created.get("id", ""), "link": created.get("htmlLink", "")}

    return await asyncio.to_thread(_do)


# ----------------------------------------------------------------------------
# Agent-facing tools
# ----------------------------------------------------------------------------
@tool(
    "gcal_status",
    "Check whether Google Calendar is connected. Use this if scheduling behavior seems off.",
    {},
)
async def gcal_status(args: dict) -> dict:
    if not is_connected():
        return _ok(
            "Google Calendar is NOT connected. Scheduling falls back to .ics files + availability "
            "rules (not busy-checked). To connect: see SETUP_GOOGLE.md, then run "
            "`python -m second_me.connect_google`."
        )
    accounts = await asyncio.to_thread(list_accounts)
    cals = await list_calendars_raw()
    n = len(cals) if cals else 0
    return _ok(
        f"Google Calendar is connected across {len(accounts)} account(s): {', '.join(accounts)}. "
        f"The agent can see {n} calendar(s) for conflict-checking and booking."
    )


@tool(
    "gcal_list_calendars",
    "List the user's Google calendars across all connected accounts (names + ids), "
    "marking the primary one and the account each belongs to.",
    {},
)
async def gcal_list_calendars(args: dict) -> dict:
    if not is_connected():
        return _err("Google Calendar not connected. Run `python -m second_me.connect_google` (see SETUP_GOOGLE.md).")
    cals = await list_calendars_raw()
    if not cals:
        return _ok("No calendars returned.")
    lines = []
    for c in cals:
        flags = " (PRIMARY)" if c["primary"] else ""
        lines.append(f"• [{c['account']}] {c['summary']}{flags} — {c['access']}\n    id: {c['id']}")
    return _ok(f"{len(cals)} calendar(s) across all accounts:\n" + "\n".join(lines))


@tool(
    "gcal_list_events",
    "List upcoming Google Calendar events in the next N days (default 7) across all calendars and accounts.",
    {"days_ahead": int},
)
async def gcal_list_events(args: dict) -> dict:
    if not is_connected():
        return _err("Google Calendar not connected. Run `python -m second_me.connect_google` (see SETUP_GOOGLE.md).")
    services = await asyncio.to_thread(get_services)
    if not services:
        return _ok("No calendars to read.")
    days_ahead = int(args.get("days_ahead") or 7)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    def _do():
        rows = []
        for email, service in services.items():
            try:
                cals = service.calendarList().list().execute().get("items", [])
            except Exception:
                continue
            for c in cals:
                try:
                    items = service.events().list(
                        calendarId=c["id"],
                        timeMin=now.isoformat(),
                        timeMax=end.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=25,
                    ).execute().get("items", [])
                except Exception:
                    continue
                for ev in items:
                    start = ev.get("start", {})
                    when = start.get("dateTime", start.get("date", "?"))
                    rows.append((when, ev.get("summary", "(no title)"), c.get("summary", ""), email))
        rows.sort(key=lambda r: r[0])
        return rows

    rows = await asyncio.to_thread(_do)
    if not rows:
        return _ok(f"No events in the next {days_ahead} days.")
    lines = [f"• {when} — {title}  [{email} / {cal}]" for when, title, cal, email in rows[:50]]
    return _ok(f"Upcoming events (next {days_ahead} days):\n" + "\n".join(lines))


GCAL_TOOLS = [gcal_status, gcal_list_calendars, gcal_list_events]

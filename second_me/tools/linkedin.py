"""LinkedIn action governor — the hard guardrail on connection requests.

Meagan opted into ONE LinkedIn workflow: the agent may VET and QUEUE connection
requests (no note) to verified ICP people — but the click that actually sends
each request is hers. The browser bridge is read-only (see permissions.py); the
agent never connects, comments, or DMs. What's governed here is the *volume and
targeting* of the batch she sends:

  - linkedin_connect_check — call BEFORE handing her each person. Enforces the
    daily cap, refuses anyone already approved (dedup), requires a stated ICP
    fit, and logs the approval. APPROVED means "vetted + logged — give this
    person to Meagan to send the request herself."
  - linkedin_connect_status — today's approved count vs the cap, recent log.

The whole capability is off unless OPERATOR_LINKEDIN_CONNECT is set (see
config.linkedin_connect_enabled); the cap is OPERATOR_LINKEDIN_DAILY_CAP
(default 50). "Today" is Meagan's day (America/Los_Angeles), not UTC. The log
is a plain file Meagan owns: data/linkedin_connects.json.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from claude_agent_sdk import tool

from ..config import (
    LINKEDIN_CONNECTS_FILE,
    ensure_dirs,
    linkedin_connect_enabled,
    linkedin_daily_cap,
)
from ._common import _err, _now, _ok, load_json_store, save_json_store

_PT = ZoneInfo("America/Los_Angeles")  # the daily cap resets on HER day, not UTC's


def _today_pt() -> str:
    return datetime.now(_PT).strftime("%Y-%m-%d")


def _norm(s: str) -> str:
    return (s or "").strip().lower().rstrip("/")


def _load() -> list:
    return load_json_store(LINKEDIN_CONNECTS_FILE, [])


def _save(log: list) -> None:
    ensure_dirs()
    save_json_store(LINKEDIN_CONNECTS_FILE, log)


def _approved_today(log: list) -> int:
    """Approvals logged during today *in Meagan's timezone* (entries store UTC)."""
    today = _today_pt()
    count = 0
    for e in log:
        try:
            at = datetime.fromisoformat(e.get("at", ""))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is not None:
            at = at.astimezone(_PT)
        if at.strftime("%Y-%m-%d") == today:
            count += 1
    return count


@tool(
    "linkedin_connect_check",
    "Call this BEFORE handing Meagan each LinkedIn connection request to send. It enforces her daily cap and "
    "refuses anyone already approved, then logs the approval. Pass the person's name and profile_url, and confirm "
    "they're a verified ICP fit (PM / CEO / CTO / Chief of Staff / COO at a seed–Series B company). APPROVED means "
    "vetted + logged — give Meagan the profile URL so SHE can send the request (no note). You never click Connect; "
    "the browser bridge is read-only. If it denies, drop the person from the batch.",
    {"name": str, "profile_url": str, "icp_fit": str},
)
async def linkedin_connect_check(args: dict) -> dict:
    if not linkedin_connect_enabled():
        return _err(
            "Connect-vetting is OFF. Meagan must enable it (set OPERATOR_LINKEDIN_CONNECT=1) before you build "
            "a connection-request batch. Until then, just surface the people and let her connect."
        )
    name = (args.get("name") or "").strip()
    url = (args.get("profile_url") or "").strip()
    if not name and not url:
        return _err("Pass at least a name or profile_url.")
    icp = (args.get("icp_fit") or "").strip()
    if not icp:
        return _err(
            "State the ICP fit (role + why they qualify) before approving — this capability is ICP-gated, not "
            "for connecting with just anyone."
        )

    log = _load()
    key_url, key_name = _norm(url), _norm(name)
    for e in log:
        if (key_url and _norm(e.get("profile_url", "")) == key_url) or (
            key_name and _norm(e.get("name", "")) == key_name
        ):
            return _err(f"Already approved a request to {name or url} on {e.get('at','')[:10]} — skip (no duplicates).")

    cap = linkedin_daily_cap()
    used = _approved_today(log)
    if used >= cap:
        return _err(
            f"Daily cap reached ({used}/{cap} approved). Stop queueing for today and tell Meagan — pushing past "
            "her normal volume is how LinkedIn flags an account."
        )

    log.append({"name": name, "profile_url": url, "icp_fit": icp, "at": _now()})
    _save(log)
    remaining = cap - (used + 1)
    return _ok(
        f"APPROVED ({used + 1}/{cap} today, {remaining} left). Vetted + logged. Now hand this to Meagan to send "
        f"herself: open {url or 'their profile'}, click Connect, 'Send without a note'. You do NOT click — the "
        "browser bridge is read-only. No note, no comment, no message."
    )


@tool(
    "linkedin_connect_status",
    "Show how many LinkedIn connection requests have been approved today (Meagan's day, Pacific) vs the daily "
    "cap, plus the most recent ones. Use to check headroom before building a batch for her to send.",
    {},
)
async def linkedin_connect_status(args: dict) -> dict:
    enabled = linkedin_connect_enabled()
    cap = linkedin_daily_cap()
    log = _load()
    used = _approved_today(log)
    state = "ON" if enabled else "OFF (set OPERATOR_LINKEDIN_CONNECT=1 to enable)"
    lines = [f"Connect-vetting: {state}. Today: {used}/{cap} approved. Total ever: {len(log)}."]
    recent = log[-5:][::-1]
    if recent:
        lines.append("Recent:")
        lines += [f"  • {e.get('at','')[:16]} — {e.get('name') or e.get('profile_url','?')}" for e in recent]
    return _ok("\n".join(lines))


# LinkedIn action governor (cap + dedup + audit). It produces a vetted batch for
# Meagan to send by hand — the browser bridge stays read-only (permissions.py),
# so there is no click path; this guardrail can't be bypassed from the browser.
LINKEDIN_TOOLS = [linkedin_connect_check, linkedin_connect_status]

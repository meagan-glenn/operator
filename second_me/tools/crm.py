"""Operator's memory: a tiny local CRM for leads, signals, and drafts.

These are the agent's "hands." Each function is exposed to Claude as a tool via
the @tool decorator. They persist to a single JSON file (data/crm.json) and a
drafts folder, so your pipeline is real state you own — not something that
evaporates when the chat ends.

To give Operator a new capability later (e.g. calendar, LinkedIn), add a new
@tool function here (or in a new module) and list it in OPERATOR_TOOLS below.
"""
from __future__ import annotations

from datetime import datetime, timezone

from claude_agent_sdk import tool

from ..config import CRM_FILE, DRAFTS_DIR, ensure_dirs
from ._common import _err, _now, _ok, _short_id, _slug, load_json_store, save_json_store

# Valid pipeline stages for a lead. Keep this short and meaningful.
LEAD_STATUSES = ["new", "researching", "outreach_sent", "in_conversation", "call_booked", "won", "lost", "nurturing"]


# ----------------------------------------------------------------------------
# Storage helpers
# ----------------------------------------------------------------------------
def _load() -> dict:
    ensure_dirs()
    return load_json_store(CRM_FILE, {"leads": [], "signals": []})


def _save(db: dict) -> None:
    ensure_dirs()
    save_json_store(CRM_FILE, db)


# ----------------------------------------------------------------------------
# Lead tools
# ----------------------------------------------------------------------------
@tool(
    "save_lead",
    "Add a founder/company to the BD pipeline. Use whenever a new potential client surfaces.",
    {"name": str, "company": str, "stage": str, "context": str, "source": str},
)
async def save_lead(args: dict) -> dict:
    db = _load()
    lead = {
        "id": _short_id(),
        "name": args.get("name", "").strip(),
        "company": args.get("company", "").strip(),
        "stage": args.get("stage", "").strip(),        # funding stage, e.g. "Seed", "Series A"
        "context": args.get("context", "").strip(),    # why they're a fit / what's going on
        "source": args.get("source", "").strip(),      # where they came from
        "status": "new",
        "created_at": _now(),
        "notes": [],
    }
    db["leads"].append(lead)
    _save(db)
    return _ok(f"Saved lead {lead['id']}: {lead['name']} @ {lead['company']} ({lead['stage']}). Status: new.")


@tool(
    "list_leads",
    "List leads in the pipeline. Pass a status to filter (one of the pipeline statuses), or 'all' for everything.",
    {"status": str},
)
async def list_leads(args: dict) -> dict:
    db = _load()
    leads = db["leads"]
    status = (args.get("status") or "all").strip().lower()
    if status and status != "all":
        leads = [l for l in leads if l.get("status") == status]
    if not leads:
        return _ok("No leads match." if status != "all" else "Pipeline is empty. Save your first lead with save_lead.")
    lines = []
    for l in leads:
        note_count = len(l.get("notes", []))
        lines.append(
            f"[{l['id']}] {l['name']} @ {l['company']} — {l['stage']} | status={l['status']} | "
            f"src={l.get('source','?')} | notes={note_count}\n      ctx: {l.get('context','')}"
        )
    header = f"{len(leads)} lead(s)" + (f" with status '{status}'" if status != "all" else "") + ":"
    return _ok(header + "\n" + "\n".join(lines))


@tool(
    "update_lead",
    "Update a lead by id: change its status and/or append a timestamped note. Leave a field blank to skip it.",
    {"lead_id": str, "status": str, "note": str},
)
async def update_lead(args: dict) -> dict:
    db = _load()
    lead_id = (args.get("lead_id") or "").strip()
    lead = next((l for l in db["leads"] if l["id"] == lead_id), None)
    if lead is None:
        return _err(f"No lead with id '{lead_id}'. Use list_leads to see ids.")

    changes = []
    new_status = (args.get("status") or "").strip().lower()
    if new_status:
        if new_status not in LEAD_STATUSES:
            return _err(f"Invalid status '{new_status}'. Valid: {', '.join(LEAD_STATUSES)}.")
        lead["status"] = new_status
        changes.append(f"status → {new_status}")

    note = (args.get("note") or "").strip()
    if note:
        lead.setdefault("notes", []).append({"at": _now(), "text": note})
        changes.append("note added")

    if not changes:
        return _ok(f"No changes for {lead_id} (pass a status and/or note).")
    _save(db)
    return _ok(f"Updated {lead_id} ({lead['name']} @ {lead['company']}): " + ", ".join(changes) + ".")


# ----------------------------------------------------------------------------
# Signal tools
# ----------------------------------------------------------------------------
@tool(
    "log_signal",
    "Capture a buying/timing signal (a raise, PM hire, launch, churn pain, etc.) so it isn't lost.",
    {"summary": str, "company": str, "source": str, "relevance": str},
)
async def log_signal(args: dict) -> dict:
    db = _load()
    signal = {
        "id": _short_id(),
        "summary": args.get("summary", "").strip(),
        "company": args.get("company", "").strip(),
        "source": args.get("source", "").strip(),
        "relevance": args.get("relevance", "").strip(),  # why it matters for Meagan
        "created_at": _now(),
    }
    db["signals"].append(signal)
    _save(db)
    return _ok(f"Logged signal {signal['id']} re: {signal['company'] or 'general'} — {signal['summary']}")


@tool(
    "list_signals",
    "List recently captured signals, newest first.",
    {"limit": int},
)
async def list_signals(args: dict) -> dict:
    db = _load()
    signals = list(reversed(db["signals"]))
    limit = args.get("limit") or 20
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    signals = signals[:limit]
    if not signals:
        return _ok("No signals logged yet. Use log_signal when you spot one.")
    lines = [
        f"[{s['id']}] {s.get('company','?')}: {s['summary']}\n      why: {s.get('relevance','')} | src: {s.get('source','?')}"
        for s in signals
    ]
    return _ok(f"{len(signals)} signal(s), newest first:\n" + "\n".join(lines))


# ----------------------------------------------------------------------------
# Draft tool
# ----------------------------------------------------------------------------
@tool(
    "save_draft",
    "Save a draft (outreach message, LinkedIn post, newsletter, TikTok script) to a markdown file for review.",
    {"kind": str, "title": str, "body": str},
)
async def save_draft(args: dict) -> dict:
    ensure_dirs()
    kind = (args.get("kind") or "draft").strip().lower().replace(" ", "_")
    title = (args.get("title") or "untitled").strip()
    body = args.get("body") or ""
    slug = _slug(title)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = DRAFTS_DIR / f"{stamp}-{kind}-{slug}.md"
    content = f"# {title}\n\n_Kind: {kind} · saved {_now()}_\n\n---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return _ok(f"Saved {kind} draft → {path}")


# BD / pipeline tools. Add new @tool functions here to extend this group.
CRM_TOOLS = [
    save_lead,
    list_leads,
    update_lead,
    log_signal,
    list_signals,
    save_draft,
]

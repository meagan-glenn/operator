"""BDR engine: the front of the funnel that finally gives the calendar legs.

Motion 1 is VC / referral-source outreach — getting Meagan on the radar of the
partners in her `VC-Fractional-Outreach-25-Funds` doc so they refer her into
portfolio founders who have the activation/churn problem her offer solves.

How this works, and its hard boundaries:

- The agent DRAFTS; Meagan SENDS. There is no auto-connecting, commenting, or
  DMing — that would risk her #1 sales channel's account. These tools research,
  draft (in her voice), and track. Her hand stays on the button.
- Two homes. The Obsidian vault is her source of truth (offer, voice, People
  notes) — the read_* tools pull from it; nothing here edits her vault. This
  module's own state (the outreach pipeline) lives in the repo at
  data/outreach.json. Notes destined for Obsidian are written to data/vault_inbox/
  for her to file herself (draft_person_note).
- Voice + pitch shape come from the vault every time (read_playbook), so drafts
  stay on-brand even as she edits her guides. Her learned rules (see memory.py)
  layer on top — e.g. "never say advisor/consultant; you're an executive for rent."

The pipeline hands off to the calendar: when a VC replies and wants to talk,
update the target to status=call_booked and use create_event to book it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from claude_agent_sdk import tool

from ..config import (
    BRAND_VOICE_FILE,
    DRAFTS_DIR,
    GIVE_FIRST_FILE,
    OFFER_FILE,
    OUTREACH_FILE,
    PEOPLE_DIR,
    VAULT_DIR,
    VAULT_INBOX_DIR,
    VC_LIST_FILE,
    ensure_dirs,
    load_outreach_framework,
    read_vault_file,
    vault_available,
)
from ._common import _err, _now, _ok, _short_id, _slug, load_json_store, save_json_store

# Where a target sits in the outreach pipeline.
OUTREACH_STATUSES = ["queued", "researching", "sent", "replied", "call_booked", "passed", "nurturing"]
# How Meagan plans to reach them. VCs skew email > DM.
CHANNELS = ["email", "linkedin_dm", "linkedin_comment", "connect_note"]
# Why this person is in the pipeline (matches the "Lens" field in her People notes).
LENSES = ["referral_source", "prospect", "amplifier", "relationship"]

_PERSON_NOTE_CAP = 8000  # cap a returned People note so a huge file doesn't flood context


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _load() -> dict:
    ensure_dirs()
    return load_json_store(OUTREACH_FILE, {"targets": []})


def _save(db: dict) -> None:
    ensure_dirs()
    save_json_store(OUTREACH_FILE, db)


def _vault_missing_msg() -> str:
    # Show the path actually checked (VAULT_DIR honors OPERATOR_VAULT — R6).
    return (
        f"Can't reach Meagan's Obsidian vault (looked for it at {VAULT_DIR}). "
        "Tell her to open the vault or set OPERATOR_VAULT, or paste the content in directly."
    )


# ----------------------------------------------------------------------------
# Read tools — pull from the vault (source of truth). These never edit it.
# ----------------------------------------------------------------------------
@tool(
    "read_playbook",
    "Load Meagan's offer + brand voice + outreach method from her vault (OFFER.md + BRAND-VOICE.md + "
    "GIVE-FIRST-METHOD.md), plus the cold email / LinkedIn DM construction framework (subject lines, word "
    "counts, follow-up cadence, channel blueprints). Call this BEFORE drafting any outreach so the message "
    "uses her real ICP, proof points, pitch shape, voice, and the Give-First circle/beat/opener structure — "
    "not a generic guess.",
    {},
)
async def read_playbook(args: dict) -> dict:
    if not vault_available():
        return _err(_vault_missing_msg())
    offer = read_vault_file(OFFER_FILE)
    voice = read_vault_file(BRAND_VOICE_FILE)
    method = read_vault_file(GIVE_FIRST_FILE)
    if not offer and not voice and not method:
        return _err(
            "Vault is reachable but OFFER.md / BRAND-VOICE.md / GIVE-FIRST-METHOD.md weren't found where expected."
        )
    parts = []
    if offer:
        parts.append("===== OFFER (Just Fractional / OFFER.md) =====\n" + offer)
    if voice:
        parts.append("===== BRAND VOICE (BRAND-VOICE.md) =====\n" + voice)
    if method:
        parts.append("===== OUTREACH METHOD (Give-First / GIVE-FIRST-METHOD.md) =====\n" + method)
    framework = load_outreach_framework()
    if framework:
        parts.append(
            "===== MESSAGE FRAMEWORK (cold email / DM construction — COLD-OUTREACH-FRAMEWORK.md) =====\n"
            + framework
        )
    return _ok("\n\n".join(parts))


@tool(
    "read_vc_targets",
    "Load Meagan's VC / referral-source target list from the vault "
    "(Just Fractional/VC-Fractional-Outreach-25-Funds.md): funds, partners, recent investments, fit notes, "
    "suggested angles, and contact paths. Use it to pick who to go after and how.",
    {},
)
async def read_vc_targets(args: dict) -> dict:
    if not vault_available():
        return _err(_vault_missing_msg())
    text = read_vault_file(VC_LIST_FILE)
    if not text:
        return _err("Vault is reachable but the VC outreach list wasn't found where expected.")
    return _ok(text)


@tool(
    "find_person",
    "Search Meagan's vault People/ notes by name and return the matching note (her relationship history, "
    "Lens, contact info, prior calls, owed follow-ups). ALWAYS check this before drafting outreach so you don't "
    "cold-pitch someone she already knows — and so you can use the warm context.",
    {"name": str},
)
async def find_person(args: dict) -> dict:
    if not vault_available():
        return _err(_vault_missing_msg())
    query = (args.get("name") or "").strip().lower()
    if not query:
        return _err("Pass a name to search for.")
    if not PEOPLE_DIR.exists():
        return _ok("No People/ folder found in the vault yet.")
    notes = sorted(PEOPLE_DIR.glob("*.md"))
    matches = [p for p in notes if query in p.stem.lower()]
    if not matches:
        return _ok(f"No People note matches '{query}'. She may not be tracked yet — treat as a fresh contact.")
    if len(matches) > 1:
        names = ", ".join(p.stem for p in matches)
        return _ok(f"Multiple People notes match '{query}': {names}. Re-run find_person with the exact name.")
    note = matches[0]
    text = read_vault_file(note)
    if len(text) > _PERSON_NOTE_CAP:
        text = text[:_PERSON_NOTE_CAP] + f"\n\n…[truncated — full note at {note}]"
    return _ok(f"Found People note: {note.stem}\n\n{text}")


# ----------------------------------------------------------------------------
# Pipeline tools — the agent's own state, in the repo (not the vault).
# ----------------------------------------------------------------------------
def create_target(name: str, org: str, channel: str, lens: str, angle: str) -> dict:
    """Create + persist an outreach target; return it. Raises ValueError on bad input.

    Shared by the add_outreach tool and discovery.promote_candidate so the target
    schema lives in exactly one place.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Pass the person's name.")
    channel = (channel or "email").strip().lower()
    if channel not in CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'. Use one of: {', '.join(CHANNELS)}.")
    lens = (lens or "referral_source").strip().lower()
    if lens not in LENSES:
        raise ValueError(f"Invalid lens '{lens}'. Use one of: {', '.join(LENSES)}.")
    db = _load()
    target = {
        "id": _short_id(),
        "name": name,
        "org": (org or "").strip(),                    # the fund (or company)
        "channel": channel,
        "lens": lens,
        "angle": (angle or "").strip(),                # the specific hook for this person
        "status": "queued",
        "next_nudge": "",
        "drafts": [],
        "notes": [],
        "created_at": _now(),
    }
    db["targets"].append(target)
    _save(db)
    return target


@tool(
    "add_outreach",
    "Add a target to the outreach pipeline (status starts at 'queued'). Use when Meagan picks someone to go "
    "after. channel: email, linkedin_dm, linkedin_comment, connect_note. lens: referral_source (a VC who refers "
    "into portfolio), prospect (a direct fractional buyer), amplifier, or relationship.",
    {"name": str, "org": str, "channel": str, "lens": str, "angle": str},
)
async def add_outreach(args: dict) -> dict:
    try:
        target = create_target(
            args.get("name"), args.get("org"), args.get("channel"), args.get("lens"), args.get("angle")
        )
    except ValueError as e:
        return _err(str(e))
    org = f" @ {target['org']}" if target["org"] else ""
    return _ok(f"Queued {target['id']}: {target['name']}{org} via {target['channel']}.")


@tool(
    "list_outreach",
    "List the outreach pipeline. Pass a status to filter (queued, researching, sent, replied, call_booked, "
    "passed, nurturing) or 'all'. Shows each target's channel, lens, status, and any owed next-nudge.",
    {"status": str},
)
async def list_outreach(args: dict) -> dict:
    db = _load()
    targets = db["targets"]
    status = (args.get("status") or "all").strip().lower()
    if status and status != "all":
        targets = [t for t in targets if t.get("status") == status]
    if not targets:
        return _ok("No targets match." if status != "all" else "Pipeline is empty. Add one with add_outreach.")
    lines = []
    for t in targets:
        nudge = f" | next: {t['next_nudge']}" if t.get("next_nudge") else ""
        org = f" @ {t['org']}" if t.get("org") else ""
        lines.append(
            f"[{t['id']}] {t['name']}{org} — {t['lens']} via {t['channel']} | status={t['status']}"
            f" | drafts={len(t.get('drafts', []))}{nudge}"
            + (f"\n      angle: {t['angle']}" if t.get("angle") else "")
        )
    header = f"{len(targets)} target(s)" + (f" with status '{status}'" if status != "all" else "") + ":"
    return _ok(header + "\n" + "\n".join(lines))


@tool(
    "update_outreach",
    "Update a target by id: change status, append a timestamped note, and/or set a next-nudge reminder. "
    "When a VC replies and wants to talk, set status=call_booked and then use create_event to book the call. "
    "Leave a field blank to skip it.",
    {"target_id": str, "status": str, "note": str, "next_nudge": str},
)
async def update_outreach(args: dict) -> dict:
    db = _load()
    target_id = (args.get("target_id") or "").strip()
    target = next((t for t in db["targets"] if t["id"] == target_id), None)
    if target is None:
        return _err(f"No target with id '{target_id}'. Use list_outreach to see ids.")

    changes = []
    new_status = (args.get("status") or "").strip().lower()
    if new_status:
        if new_status not in OUTREACH_STATUSES:
            return _err(f"Invalid status '{new_status}'. Valid: {', '.join(OUTREACH_STATUSES)}.")
        target["status"] = new_status
        changes.append(f"status → {new_status}")

    note = (args.get("note") or "").strip()
    if note:
        target.setdefault("notes", []).append({"at": _now(), "text": note})
        changes.append("note added")

    nudge = (args.get("next_nudge") or "").strip()
    if nudge:
        target["next_nudge"] = nudge
        changes.append(f"next nudge → {nudge}")

    if not changes:
        return _ok(f"No changes for {target_id} (pass status, note, and/or next_nudge).")
    _save(db)
    return _ok(f"Updated {target_id} ({target['name']}): " + ", ".join(changes) + ".")


@tool(
    "save_outreach_draft",
    "Save a drafted message for a target (so Meagan can review and send it). channel: email, linkedin_dm, "
    "linkedin_comment, connect_note. For email, include a subject. The draft is written to a markdown file and "
    "linked to the target. Draft in Meagan's voice — call read_playbook first; these are conversation-starters, "
    "NOT pitches.",
    {"target_id": str, "channel": str, "subject": str, "body": str},
)
async def save_outreach_draft(args: dict) -> dict:
    db = _load()
    target_id = (args.get("target_id") or "").strip()
    target = next((t for t in db["targets"] if t["id"] == target_id), None)
    if target is None:
        return _err(f"No target with id '{target_id}'. Use list_outreach to see ids.")
    channel = (args.get("channel") or target.get("channel") or "email").strip().lower()
    if channel not in CHANNELS:
        return _err(f"Invalid channel '{channel}'. Use one of: {', '.join(CHANNELS)}.")
    body = args.get("body") or ""
    if not body.strip():
        return _err("Draft body is empty.")
    subject = (args.get("subject") or "").strip()

    ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = DRAFTS_DIR / f"{stamp}-outreach-{channel}-{_slug(target['name'], 40)}.md"
    header = f"# Outreach → {target['name']}"
    if target.get("org"):
        header += f" @ {target['org']}"
    meta = f"_Channel: {channel} · {target['lens']} · saved {_now()}_"
    subj_line = f"\n\n**Subject:** {subject}" if subject else ""
    path.write_text(f"{header}\n\n{meta}{subj_line}\n\n---\n\n{body}\n", encoding="utf-8")

    target.setdefault("drafts", []).append(
        {"channel": channel, "subject": subject, "path": str(path), "at": _now()}
    )
    _save(db)
    return _ok(f"Saved {channel} draft for {target['name']} → {path}\nReview and send it yourself when you're ready.")


@tool(
    "draft_person_note",
    "Write a vault-format People note to data/vault_inbox/ for Meagan to drop into her Obsidian People/ folder. "
    "Use after a call or when a new contact is worth tracking. Match her format: a top block with "
    "**Relationship:**, **Lens:**, **Based:**, **Background:**, **Contact:**, then ## Context and "
    "## Open follow-ups (as - [ ] checkboxes). Pass the whole note as 'body'. This does NOT touch her vault — "
    "it stages the note for her to file.",
    {"name": str, "body": str},
)
async def draft_person_note(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    body = args.get("body") or ""
    if not name:
        return _err("Pass the person's name.")
    if not body.strip():
        return _err("Pass the note body (vault-format markdown).")
    ensure_dirs()
    path = VAULT_INBOX_DIR / f"{_slug(name, 60)}.md"
    # If the body doesn't already start with a title, add one.
    content = body if body.lstrip().startswith("#") else f"# {name}\n\n{body}"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return _ok(
        f"Staged a People note for {name} → {path}\n"
        "It's NOT in your vault yet — review it, then move it into your Obsidian People/ folder."
    )


# BDR / outreach tools. Motion 1 = VC / referral-source outreach.
BDR_TOOLS = [
    read_playbook,
    read_vc_targets,
    find_person,
    add_outreach,
    list_outreach,
    update_outreach,
    save_outreach_draft,
    draft_person_note,
]

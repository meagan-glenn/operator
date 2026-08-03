"""Discovery engine: the agent actively hunts for fresh prospects, daily.

Meagan doesn't keep a static list — she wants a "second me" that goes looking
every day for two kinds of people and hands her a fresh, deduped, ranked batch:

  - referral sources (VCs investing seed–Series B SaaS who refer operators in)
  - direct-fit founders (seed–Series B SaaS with a churn/activation problem)

How the pieces split:

- The SEARCHING is the agent's job, using its built-in web tools (WebSearch /
  WebFetch) across funding news, the open web, and Reddit complaint passes
  (r/saas, r/startups, r/entrepreneur — founders self-reporting product pain).
  LinkedIn-via-Chrome is a planned source, not wired yet; until then Meagan can
  paste LinkedIn content in and the agent treats it as a source.
- These TOOLS persist + dedup what the agent finds, so each day's batch is
  genuinely new — nobody already in the candidate store, already in the outreach
  pipeline, or already known in her vault gets re-served. The agent scores fit
  against her real offer (read_playbook) and saves candidates; Meagan reviews and
  promotes the ones she likes, which drops them into the outreach pipeline
  (reusing bdr.create_target). Discovery never reaches out on its own.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from claude_agent_sdk import tool

from ..config import (
    CANDIDATES_FILE,
    CRM_FILE,
    LINKEDIN_DIR,
    OUTREACH_FILE,
    PEOPLE_DIR,
    ensure_dirs,
    vault_available,
)
from ._common import _err, _now, _ok, _short_id, load_json_store, save_json_store
from .bdr import create_target

CANDIDATE_TYPES = ["vc", "founder"]
# Lifecycle: new (never shown) → surfaced (auto-set the moment list_candidates
# shows someone, so the same faces don't come back every ask) → reviewed /
# promoted / dismissed (Meagan's explicit triage).
CANDIDATE_STATUSES = ["new", "surfaced", "reviewed", "promoted", "dismissed"]

# Title keywords used to classify a LinkedIn connection. VC checked first because
# "Partner"/"Investor" is a strong signal even when "founder" also appears.
_VC_ROLES = ("partner", "general partner", "managing partner", "venture", "ventures",
             "investor", "principal", "angel", "capital", " vc")
_FOUNDER_ROLES = ("founder", "co-founder", "cofounder", "ceo", "chief executive", "coo",
                  "chief operating", "cto", "chief technology", "cpo", "chief product",
                  "head of product", "vp product", "vp of product", "owner", "president")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _key(name: str, org: str) -> str:
    return f"{(name or '').strip().lower()}|{(org or '').strip().lower()}"


def _load() -> dict:
    ensure_dirs()
    return load_json_store(CANDIDATES_FILE, {"candidates": []})


def _save(db: dict) -> None:
    ensure_dirs()
    save_json_store(CANDIDATES_FILE, db)


def _outreach_keys() -> set[str]:
    """Name|org keys already in the outreach pipeline, so we don't re-discover them."""
    db = load_json_store(OUTREACH_FILE, {"targets": []})
    return {_key(t.get("name", ""), t.get("org", "")) for t in db.get("targets", [])}


def _crm_keys() -> set[str]:
    """Name|company keys already tracked as CRM leads (R9 — one pipeline, no re-discovery)."""
    db = load_json_store(CRM_FILE, {"leads": [], "signals": []})
    return {_key(l.get("name", ""), l.get("company", "")) for l in db.get("leads", [])}


def _known_in_vault(name: str) -> bool:
    """True if a People/ note already exists for this person.

    Matching: exact stem match, or every token of the shorter name appears as a
    whole word in the longer one ("Jane Doe" matches "Jane Doe (Acme)"). Whole-
    word containment avoids the substring false-positives the old bidirectional
    `in` check had (e.g. "Al" matching "Alyssa").
    """
    if not vault_available() or not PEOPLE_DIR.exists():
        return False
    n = (name or "").strip().lower()
    if not n:
        return False
    n_tokens = n.split()
    for p in PEOPLE_DIR.glob("*.md"):
        stem = p.stem.lower()
        if n == stem:
            return True
        stem_tokens = stem.split()
        shorter, longer = sorted([n_tokens, stem_tokens], key=len)
        if shorter and all(t in longer for t in shorter):
            return True
    return False


def _coerce_score(raw) -> int:
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 3


def _seen_keys(db: dict) -> set[str]:
    """All name|org keys already taken — candidate store + outreach pipeline + CRM leads."""
    return {_key(c["name"], c.get("org", "")) for c in db["candidates"]} | _outreach_keys() | _crm_keys()


def _add_candidate(db: dict, seen: set[str], *, name: str, ctype: str, org: str, stage: str,
                   signal: str, fit_reason: str, fit_score, source: str, relationship: str = "") -> dict | None:
    """Append a genuinely-new candidate to db and return it, or None if a duplicate.

    `seen` is the live set of taken keys (mutated on success) so a single bulk
    import dedups within itself as well as against the stores.
    """
    name = (name or "").strip()
    if not name:
        return None
    org = (org or "").strip()
    key = _key(name, org)
    if key in seen:
        return None
    cand = {
        "id": _short_id(),
        "name": name,
        "type": ctype,
        "org": org,
        "stage": (stage or "").strip(),
        "signal": (signal or "").strip(),
        "fit_reason": (fit_reason or "").strip(),
        "fit_score": _coerce_score(fit_score),
        "source": (source or "").strip(),
        "relationship": (relationship or "").strip(),   # connection / follow / "" (web discovery)
        "known": _known_in_vault(name),
        "status": "new",
        "created_at": _now(),
    }
    db["candidates"].append(cand)
    seen.add(key)
    return cand


def _mark_surfaced(batch: list[dict]) -> int:
    """Flip status new → surfaced (with a timestamp) on just-shown candidates.

    This is the fix for the original failure mode: presenting a candidate and
    reviewing them are different events, and only the human does the second one.
    Recording the first automatically means the next default listing serves
    genuinely unseen people instead of the same top-ranked faces every ask.
    Returns how many were newly marked (already-surfaced/triaged ones are left
    alone, so re-listing on request doesn't reset anyone's real status).
    """
    marked = 0
    for c in batch:
        if c.get("status") == "new":
            c["status"] = "surfaced"
            c["surfaced_at"] = _now()
            marked += 1
    return marked


def _classify_role(position: str) -> str | None:
    """Map a LinkedIn job title to 'vc', 'founder', or None (not a fit to surface)."""
    p = (position or "").lower()
    if any(k in p for k in _VC_ROLES):
        return "vc"
    if any(k in p for k in _FOUNDER_ROLES):
        return "founder"
    return None


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------
@tool(
    "save_candidate",
    "Save a prospect the agent discovered (during a daily pass) for Meagan to review. type: 'vc' (a referral "
    "source) or 'founder' (a direct-fit buyer). Include the timing 'signal' (e.g. 'raised $4M seed Feb 2026', "
    "'posting about churn on r/saas'), a short 'fit_reason' vs her ICP, a 'source' URL, and fit_score 1-5 (5 = "
    "ideal fit). Automatically skips anyone already discovered, already in the outreach pipeline. Flags people "
    "she already knows (a vault People note) instead of pretending they're cold.",
    {"name": str, "type": str, "org": str, "stage": str, "signal": str, "fit_reason": str, "fit_score": int, "source": str},
)
async def save_candidate(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return _err("Pass the prospect's name (a person, or a company if the founder isn't named yet).")
    ctype = (args.get("type") or "").strip().lower()
    if ctype not in CANDIDATE_TYPES:
        return _err(f"Invalid type '{ctype}'. Use 'vc' or 'founder'.")
    org = (args.get("org") or "").strip()

    db = _load()
    cand = _add_candidate(
        db, _seen_keys(db), name=name, ctype=ctype, org=org, stage=args.get("stage"),
        signal=args.get("signal"), fit_reason=args.get("fit_reason"),
        fit_score=args.get("fit_score"), source=args.get("source"),
    )
    if cand is None:
        return _ok(f"{name}" + (f" @ {org}" if org else "") + " is already known (discovered or in pipeline) — skipped.")
    _save(db)
    flag = "  ⚠ she already knows this person (vault note exists) — treat as warm" if cand["known"] else ""
    return _ok(
        f"Saved candidate {cand['id']}: {name}" + (f" @ {org}" if org else "")
        + f" [{ctype}, fit {cand['fit_score']}/5]{flag}"
    )


@tool(
    "list_candidates",
    "Show discovered prospects awaiting review. Defaults to status 'new' — people NEVER shown before — and "
    "auto-marks everyone it returns as 'surfaced' so they don't come back on the next ask. Only re-serve "
    "someone when Meagan explicitly asks (status 'surfaced' = shown but untriaged; also reviewed/promoted/"
    "dismissed/all). Filter by type ('vc'/'founder') and min_score (1-5). Sorted by fit score, highest first.",
    {"type": str, "status": str, "min_score": int, "limit": int},
)
async def list_candidates(args: dict) -> dict:
    db = _load()
    cands = db["candidates"]
    ctype = (args.get("type") or "").strip().lower()
    if ctype in CANDIDATE_TYPES:
        cands = [c for c in cands if c.get("type") == ctype]
    status = (args.get("status") or "new").strip().lower()
    if status and status != "all":
        cands = [c for c in cands if c.get("status") == status]
    min_score = _coerce_score(args.get("min_score")) if args.get("min_score") else 1
    cands = [c for c in cands if c.get("fit_score", 0) >= min_score]
    cands.sort(key=lambda c: (-c.get("fit_score", 0), c.get("created_at", "")))
    limit = int(args.get("limit") or 25)
    cands = cands[:limit]
    if not cands:
        surfaced = sum(1 for c in db["candidates"] if c.get("status") == "surfaced")
        msg = "No unseen candidates match."
        if status == "new" and surfaced:
            msg += (f" ({surfaced} previously shown candidate(s) are still untriaged — pass status "
                    "'surfaced' if Meagan wants to revisit them.)")
        return _ok(msg + " Run a discovery pass (search funding news + Reddit) to fill the batch.")
    if _mark_surfaced(cands):
        _save(db)
    lines = []
    for c in cands:
        org = f" @ {c['org']}" if c.get("org") else ""
        known = " ⚠known" if c.get("known") else ""
        warm = f" ·warm:{c['relationship']}" if c.get("relationship") in ("connection", "follow") else ""
        stage = f" | {c['stage']}" if c.get("stage") else ""
        lines.append(
            f"[{c['id']}] {c['name']}{org} — {c['type']} | fit {c.get('fit_score','?')}/5{stage}{warm}{known}\n"
            f"      signal: {c.get('signal','')}\n"
            f"      fit: {c.get('fit_reason','')}" + (f" | src: {c['source']}" if c.get("source") else "")
        )
    header = f"{len(cands)} candidate(s)" + (f", status '{status}'" if status != "all" else "") + ", best fit first"
    if status == "new":
        header += " (now marked 'surfaced' — they won't repeat on the next ask)"
    return _ok(header + ":\n" + "\n".join(lines))


@tool(
    "update_candidate",
    "Update a discovered candidate by id: set status (new, surfaced, reviewed, dismissed) and/or attach a note. "
    "Use 'dismissed' when Meagan passes on someone, 'reviewed' when she's seen them and is thinking, 'new' to "
    "deliberately requeue someone for the next batch. To move someone into active outreach, use "
    "promote_candidate instead.",
    {"candidate_id": str, "status": str, "note": str},
)
async def update_candidate(args: dict) -> dict:
    db = _load()
    cid = (args.get("candidate_id") or "").strip()
    cand = next((c for c in db["candidates"] if c["id"] == cid), None)
    if cand is None:
        return _err(f"No candidate with id '{cid}'. Use list_candidates to see ids.")
    changes = []
    status = (args.get("status") or "").strip().lower()
    if status:
        if status not in CANDIDATE_STATUSES:
            return _err(f"Invalid status '{status}'. Valid: {', '.join(CANDIDATE_STATUSES)}.")
        cand["status"] = status
        changes.append(f"status → {status}")
    note = (args.get("note") or "").strip()
    if note:
        cand.setdefault("notes", []).append({"at": _now(), "text": note})
        changes.append("note added")
    if not changes:
        return _ok(f"No changes for {cid} (pass a status and/or note).")
    _save(db)
    return _ok(f"Updated candidate {cid} ({cand['name']}): " + ", ".join(changes) + ".")


@tool(
    "promote_candidate",
    "Promote a discovered candidate into the outreach pipeline once Meagan wants to pursue them. Creates an "
    "outreach target (lens is set automatically: vc → referral_source, founder → prospect) and marks the "
    "candidate 'promoted'. channel: email, linkedin_dm, linkedin_comment, connect_note. Then draft the opener "
    "with save_outreach_draft. Remember to find_person first if they might be known.",
    {"candidate_id": str, "channel": str, "angle": str},
)
async def promote_candidate(args: dict) -> dict:
    db = _load()
    cid = (args.get("candidate_id") or "").strip()
    cand = next((c for c in db["candidates"] if c["id"] == cid), None)
    if cand is None:
        return _err(f"No candidate with id '{cid}'. Use list_candidates to see ids.")
    if cand.get("status") == "promoted":
        return _ok(f"{cand['name']} is already promoted (target {cand.get('target_id','?')}).")
    lens = "referral_source" if cand["type"] == "vc" else "prospect"
    rel = cand.get("relationship", "")
    if rel == "connection":
        default_channel = "linkedin_dm"      # already connected — DM directly, no request needed
    elif rel == "follow":
        default_channel = "connect_note"     # not connected yet — connect first, then DM
    else:
        default_channel = "email" if cand["type"] == "vc" else "linkedin_dm"
    channel = (args.get("channel") or default_channel).strip().lower()
    angle = (args.get("angle") or cand.get("signal") or cand.get("fit_reason") or "").strip()
    try:
        target = create_target(cand["name"], cand.get("org", ""), channel, lens, angle)
    except ValueError as e:
        return _err(str(e))
    cand["status"] = "promoted"
    cand["target_id"] = target["id"]
    _save(db)
    return _ok(
        f"Promoted {cand['name']} → outreach target {target['id']} ({lens} via {channel}). "
        "Draft the opener with save_outreach_draft (read_playbook first), then send it yourself."
    )


@tool(
    "import_linkedin_connections",
    "Ingest Meagan's LinkedIn connections (or follows) CSV export and stage the role-matched people as WARM "
    "candidates — her own network is the best source (she can DM connections without a request). To get the "
    "file: LinkedIn > Settings > Data privacy > Get a copy of your data > Connections; she drops the CSV into "
    "data/linkedin/. Pass 'path' to point at a specific file, or leave blank to use the newest CSV there. "
    "relationship: 'connection' (default, already connected) or 'follow' (not yet connected). The import is "
    "role-matched but stage-UNVERIFIED — web-verify each company is seed–Series B SaaS before drafting.",
    {"path": str, "relationship": str, "limit": int},
)
async def import_linkedin_connections(args: dict) -> dict:
    ensure_dirs()
    rel = (args.get("relationship") or "connection").strip().lower()
    if rel not in ("connection", "follow"):
        rel = "connection"

    raw = (args.get("path") or "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        csvs = sorted(LINKEDIN_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not csvs:
            return _err(
                "No CSV found. Export your connections (LinkedIn > Settings > Data privacy > Get a copy of "
                f"your data > Connections), then drop the file into {LINKEDIN_DIR} and try again."
            )
        path = csvs[0]
    if not path.exists():
        return _err(f"File not found: {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return _err(f"Couldn't read {path}: {e}")

    # LinkedIn prepends a few "Notes:" lines before the real header — skip to it.
    lines = text.splitlines()
    hdr = next((i for i, l in enumerate(lines) if "first name" in l.lower() and "last name" in l.lower()), None)
    if hdr is None:
        return _err("That doesn't look like a LinkedIn connections export (no First Name / Last Name header row).")
    reader = csv.DictReader(io.StringIO("\n".join(lines[hdr:])))

    db = _load()
    seen = _seen_keys(db)
    limit = int(args.get("limit") or 150)
    read = matched = saved = founders = vcs = 0
    examples: list[str] = []
    for row in reader:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = f"{r.get('first name', '')} {r.get('last name', '')}".strip()
        if not name:
            continue
        read += 1
        position, company, url = r.get("position", ""), r.get("company", ""), r.get("url", "")
        ctype = _classify_role(position)
        if ctype is None:
            continue
        matched += 1
        if saved >= limit:
            continue
        score = 4 if (ctype == "founder" and ("founder" in position.lower() or "ceo" in position.lower())) else 3
        signal = f"{rel.title()} — {position}".strip(" —") + (f" @ {company}" if company else "") + " (stage unverified)"
        fit = f"Role match from your LinkedIn {rel}s. Verify the company is seed–Series B SaaS before drafting."
        cand = _add_candidate(
            db, seen, name=name, ctype=ctype, org=company, stage="", signal=signal,
            fit_reason=fit, fit_score=score, source=url, relationship=rel,
        )
        if cand is None:
            continue
        saved += 1
        founders += ctype == "founder"
        vcs += ctype == "vc"
        if len(examples) < 5:
            examples.append(f"{name} ({position})")
    _save(db)

    if matched == 0:
        return _ok(
            f"Read {read} {rel}(s), but none matched founder/exec or VC titles "
            "(looked for Founder, CEO, COO, CPO, Head of Product, Partner, Investor, etc.)."
        )
    msg = (
        f"Imported your LinkedIn {rel}s: read {read}, role-matched {matched}, saved {saved} new warm "
        f"candidate(s) ({founders} founders, {vcs} VCs)."
    )
    if saved < matched:
        msg += f" {matched - saved} were already known or in the pipeline (or past the {limit} cap)."
    if examples:
        msg += "\nExamples: " + "; ".join(examples)
    msg += (
        "\nThese are role-matched but stage-UNVERIFIED — review with list_candidates, then I'll web-verify "
        "each company is seed–Series B SaaS before we draft anything. Same hard rule: you send, not me."
    )
    return _ok(msg)


# Discovery tools. The agent hunts (web + her own network); these persist + dedup; Meagan reviews.
DISCOVERY_TOOLS = [
    save_candidate,
    list_candidates,
    update_candidate,
    promote_candidate,
    import_linkedin_connections,
]

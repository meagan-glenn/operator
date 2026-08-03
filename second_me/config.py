"""Central paths and settings for the Operator agent.

Everything Operator knows about itself and remembers lives under this project,
in plain files you own: identity.md (who it is) and data/ (what it remembers).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Project layout
PACKAGE_DIR = Path(__file__).resolve().parent          # .../operator/second_me
PROJECT_ROOT = PACKAGE_DIR.parent                       # .../operator


def _load_dotenv(path: Path) -> None:
    """Load a local .env (KEY=VALUE lines) if present, so settings like
    OPERATOR_CHROME_MCP_URL work without exporting them in the shell.

    Dependency-free and safe by design: the real shell environment always wins
    (setdefault), and a missing or garbled file never raises (R7 graceful
    degradation). Runs before the os.environ reads below so they see the values.
    """
    try:
        if not path.exists():
            return
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)
    except Exception:
        pass


_load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
DRAFTS_DIR = DATA_DIR / "drafts"
CALENDAR_DIR = DATA_DIR / "calendar"                    # generated .ics files live here
CRM_FILE = DATA_DIR / "crm.json"
EVENTS_FILE = DATA_DIR / "events.json"                  # index of created calendar events
RULES_FILE = DATA_DIR / "learned_rules.json"            # rules Operator learns from Meagan's corrections
OUTREACH_FILE = DATA_DIR / "outreach.json"              # BDR outreach pipeline (VCs + prospects)
CANDIDATES_FILE = DATA_DIR / "candidates.json"          # discovered prospects awaiting Meagan's review
LINKEDIN_DIR = DATA_DIR / "linkedin"                    # LinkedIn exports she drops in (Connections.csv, follows)
LINKEDIN_CONNECTS_FILE = DATA_DIR / "linkedin_connects.json"  # audit log of connection requests sent (cap + dedup)
VAULT_INBOX_DIR = DATA_DIR / "vault_inbox"              # notes the agent prepped for Meagan to file into Obsidian

# --- LinkedIn connect-vetting (opt-in, off by default) -------------------------
# When enabled, the agent may VET + LOG connection-request candidates (no note,
# verified ICP only) via the linkedin_connect_check governor and hand Meagan the
# batch to send herself — there is NO browser click path; sending is always hers.
# Enable with OPERATOR_LINKEDIN_CONNECT=1; cap the daily approvals with
# OPERATOR_LINKEDIN_DAILY_CAP (her norm is 50-100/day).
def linkedin_connect_enabled() -> bool:
    return os.environ.get("OPERATOR_LINKEDIN_CONNECT", "").strip().lower() in {"1", "true", "yes", "on"}


def linkedin_daily_cap() -> int:
    try:
        return max(1, int(os.environ.get("OPERATOR_LINKEDIN_DAILY_CAP", "50")))
    except ValueError:
        return 50
IDENTITY_FILE = PACKAGE_DIR / "identity.md"
# Scheduling rules come in two layers: the packaged file is a generic, committed
# EXAMPLE (safe to publish); your real schedule lives in data/availability.json
# (gitignored, wins when present) so it never has to be committed.
AVAILABILITY_FILE = PACKAGE_DIR / "availability.json"
LOCAL_AVAILABILITY_FILE = DATA_DIR / "availability.json"

# Model: Sonnet is a great default for a high-volume personal operator.
# Swap to "claude-opus-4-8" via the OPERATOR_MODEL env var when you want max horsepower.
MODEL = os.environ.get("OPERATOR_MODEL", "claude-sonnet-4-6")

# ----------------------------------------------------------------------------
# The Obsidian vault — Meagan's source of truth (READ-mostly).
#
# Two homes, and the agent moves between them: the vault holds her hand-curated
# relationships (People/), the offer, and the voice guide — the agent READS these
# but never silently edits her notes. The repo (data/ above) is the agent's own
# workbench for drafts + pipeline state. Anything the agent wants to land in
# Obsidian goes to VAULT_INBOX_DIR for Meagan to file herself.
#
# Override the location with the OPERATOR_VAULT env var.
# ----------------------------------------------------------------------------
VAULT_DIR = Path(os.environ.get("OPERATOR_VAULT", str(Path.home() / "Documents" / "Obsidian Vault")))
JUST_FRACTIONAL_DIR = VAULT_DIR / "Just Fractional"
PEOPLE_DIR = VAULT_DIR / "People"
OFFER_FILE = JUST_FRACTIONAL_DIR / "OFFER.md"
BRAND_VOICE_FILE = VAULT_DIR / "BRAND-VOICE.md"
VC_LIST_FILE = JUST_FRACTIONAL_DIR / "VC-Fractional-Outreach-25-Funds.md"
GIVE_FIRST_FILE = JUST_FRACTIONAL_DIR / "GIVE-FIRST-METHOD.md"   # outreach methodology (circles/beats/opener)

# Message-construction framework (subject lines, word counts, cadence, channel
# blueprints) — the sentence-level layer under GIVE-FIRST-METHOD.md's strategy.
# The packaged copy ships with the repo as editable prose (like identity.md);
# if Meagan files her own copy into the vault it wins, so she can take ownership
# of it in Obsidian alongside the rest of the playbook.
OUTREACH_FRAMEWORK_FILE = PACKAGE_DIR / "outreach_framework.md"
VAULT_OUTREACH_FRAMEWORK_FILE = JUST_FRACTIONAL_DIR / "COLD-OUTREACH-FRAMEWORK.md"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    LINKEDIN_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_INBOX_DIR.mkdir(parents=True, exist_ok=True)


def load_identity() -> str:
    """The agent's persona (identity.md), or a minimal stub if unreadable (R7)."""
    try:
        return IDENTITY_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (
            "You are Operator, Meagan's personal AI agent for business development, "
            "outreach drafting, and scheduling.\n\n"
            f"WARNING: your identity file ({IDENTITY_FILE}) could not be read, so your "
            "full persona, voice, and priorities are missing this session. Tell Meagan "
            "to restore identity.md, and be conservative until she does."
        )


# Built-in scheduling defaults, shape-matched to availability.json. Used only if
# that file is missing/unparseable so scheduling never crashes the agent (R7).
_AVAILABILITY_DEFAULTS: dict = {
    "timezone": "America/Los_Angeles",
    "working_hours": {"start": "06:00", "end": "14:00"},
    "default_call_minutes": 30,
    "buffer_minutes": 15,
    "no_meeting_days": ["Saturday", "Sunday"],
    "protected_blocks": [],
    "google": {},
}

# Set when the last load_availability() fell back to defaults; surfaced in the
# system prompt (agent.py) so the degradation is visible, not silent.
_availability_error: str | None = None
# Which file the last load_availability() actually used — surfaced in the CLI
# banner so "running on the generic example" is visible, never silent (the
# example would suggest wrong hours and book to the wrong account).
_availability_source: str = "built-in defaults"


def availability_load_error() -> str | None:
    """Why the last load_availability() used built-in defaults, or None if it didn't."""
    return _availability_error


def availability_source() -> str:
    """Which file the last load_availability() used (personal / packaged example / defaults)."""
    return _availability_source


def load_availability() -> dict:
    """Meagan's scheduling rules (timezone, working hours, protected blocks).

    The personal copy (data/availability.json, gitignored) wins over the packaged
    example. Never raises: an unparseable file, or neither file existing, falls
    back to _AVAILABILITY_DEFAULTS and records the reason for
    availability_load_error(). A personal copy with a parse error does NOT fall
    through to the example — that would silently swap in the wrong schedule.
    """
    global _availability_error, _availability_source
    for path, label in ((LOCAL_AVAILABILITY_FILE, "personal (data/availability.json)"),
                        (AVAILABILITY_FILE, "packaged example (second_me/availability.json)")):
        if not path.exists():
            continue
        try:
            av = json.loads(path.read_text(encoding="utf-8"))
            _availability_error = None
            _availability_source = label
            return av
        except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            _availability_error = f"{path.name}: {e}"
            _availability_source = "built-in defaults"
            return dict(_AVAILABILITY_DEFAULTS)
    _availability_error = f"{AVAILABILITY_FILE.name}: not found"
    _availability_source = "built-in defaults"
    return dict(_AVAILABILITY_DEFAULTS)


def _quarantine_corrupt(path: Path) -> None:
    """Best-effort rename of an unparseable JSON file to <name>.corrupt-<stamp>.

    A tiny private copy of tools/_common.py's quarantine logic — config.py can't
    import from tools/ (import cycle). Keep the two in sync.
    """
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path.rename(path.with_name(f"{path.name}.corrupt-{stamp}"))
    except OSError:
        pass


def load_rules() -> list:
    """Rules Operator has learned about how Meagan wants it to work.

    These accumulate across sessions (written by the remember_rule tool) and are
    injected into the system prompt so a correction never has to be made twice.
    Degrades to an empty list if the file is missing or unreadable; an unparseable
    file is quarantined (renamed .corrupt-<stamp>) so the next save can't clobber it.
    """
    if not RULES_FILE.exists():
        return []
    try:
        return json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        _quarantine_corrupt(RULES_FILE)
        return []


def load_outreach_framework() -> str:
    """The cold email / LinkedIn DM construction framework.

    Prefers a copy Meagan has filed into the vault (her source of truth wins);
    falls back to the packaged default. Returns '' if neither is readable —
    drafting then leans on the distilled floor in agent.py's _bdr_block (R7).
    """
    text = read_vault_file(VAULT_OUTREACH_FRAMEWORK_FILE)
    if text:
        return text
    try:
        return OUTREACH_FRAMEWORK_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def vault_available() -> bool:
    """True if Meagan's Obsidian vault is reachable on this machine."""
    return VAULT_DIR.exists()


def read_vault_file(path: Path) -> str:
    """Read a vault file, or return '' if it's missing/unreadable.

    The vault is an external source of truth that may not be present in every
    environment, so reads must never crash the agent.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""

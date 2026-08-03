"""Google OAuth + Calendar service builder (multi-account).

Google libraries are imported lazily inside functions so the rest of the agent
runs even before you've installed them / connected Google. Until you connect any
account, `get_services()` returns {} and the calendar tools fall back to .ics +
rules.

You can connect more than one Google account (e.g. a personal gmail and a work
domain). Each account gets its own token file under data/google_tokens/, named by
the account's email. Conflict-checking spans ALL connected accounts; booking goes
to whichever account you configure (see availability.json -> google).

One-time setup lives in SETUP_GOOGLE.md. After that, run once per account:
    python -m second_me.connect_google
"""
from __future__ import annotations

from pathlib import Path

from .config import DATA_DIR, PROJECT_ROOT, ensure_dirs

# Read/write access to your calendars (needed for freebusy + creating events).
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# You download this from Google Cloud Console (see SETUP_GOOGLE.md).
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"

# One token file per connected account, named "<email>.json".
TOKENS_DIR = DATA_DIR / "google_tokens"
# Pre-multi-account token location; migrated into TOKENS_DIR on first use.
LEGACY_TOKEN_FILE = DATA_DIR / "google_token.json"


def has_credentials() -> bool:
    """True if the downloaded OAuth client secrets file is in place."""
    return CREDENTIALS_FILE.exists()


def _token_path(email: str) -> Path:
    return TOKENS_DIR / f"{email}.json"


def _load_creds_from(path: Path):
    """Return valid Credentials from a token file (refreshing if needed), or None."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return None


def _build_service(creds):
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _account_email(creds) -> str:
    """The account's email == the id of its primary calendar."""
    service = _build_service(creds)
    return service.calendarList().get(calendarId="primary").execute()["id"]


def _migrate_legacy() -> None:
    """Move a pre-multi-account google_token.json into TOKENS_DIR (runs once)."""
    if not LEGACY_TOKEN_FILE.exists():
        return
    try:
        creds = _load_creds_from(LEGACY_TOKEN_FILE)
        if creds is None:
            return
        email = _account_email(creds)
    except Exception:
        return  # offline / bad token — leave the legacy file in place for next time
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _token_path(email)
    if not dest.exists():
        dest.write_text(creds.to_json(), encoding="utf-8")
    try:
        LEGACY_TOKEN_FILE.unlink()
    except OSError:
        pass


def list_accounts() -> list[str]:
    """Emails of all connected accounts (migrates a legacy token first)."""
    _migrate_legacy()
    if not TOKENS_DIR.exists():
        return []
    return sorted(p.stem for p in TOKENS_DIR.glob("*.json"))


def is_connected() -> bool:
    """True if at least one Google account is connected."""
    return len(list_accounts()) > 0


def get_services() -> dict:
    """{email: authenticated Calendar client} for every connected account."""
    out: dict = {}
    for email in list_accounts():
        try:
            creds = _load_creds_from(_token_path(email))
        except Exception:
            creds = None
        if creds is not None:
            out[email] = _build_service(creds)
    return out


def get_service(account: str | None = None):
    """Authenticated Calendar client for one account, or None if not connected.

    With `account`, returns that account's client. Without, returns the first
    connected account's client (back-compat for single-account call sites).
    """
    accounts = list_accounts()
    if not accounts:
        return None
    email = account or accounts[0]
    try:
        creds = _load_creds_from(_token_path(email))
    except Exception:
        return None
    if creds is None:
        return None
    return _build_service(creds)


def connect_interactive() -> str:
    """Run the one-time browser OAuth flow for ONE account; persist + return its email."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {CREDENTIALS_FILE}. Download your OAuth client secrets from Google "
            "Cloud Console and save them there. See SETUP_GOOGLE.md."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    email = _account_email(creds)
    ensure_dirs()
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    _token_path(email).write_text(creds.to_json(), encoding="utf-8")
    return email

"""Shared helpers for Operator's tool modules.

Every tool module needs the same small kit: SDK content-dict builders
(_ok/_err — see R3), timestamps, short ids, slugs, and JSON-store IO. They
live here once instead of being copy-pasted per module.

The JSON-store helpers are deliberately paranoid about Meagan's data (R7,
and these files ARE the agent's memory):

- save_json_store writes to a temp file in the same directory and then
  os.replace()s it into place, so a crash mid-write can never leave a
  half-written (= corrupt) store behind.
- load_json_store never raises; if a file exists but won't parse, it is
  renamed aside to "<name>.corrupt-<UTC stamp>" (best-effort) before the
  default is returned — so the broken state is preserved for recovery
  instead of being silently overwritten on the next save.

NOTE: config.py cannot import from this module (it would create an import
cycle through tools/__init__.py), so it keeps a tiny private copy of the
corrupt-file-rename logic. If you change the quarantine behavior here,
mirror it there.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def _now() -> str:
    """Current UTC time as an ISO-8601 string (the storage format for timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _slug(text: str, limit: int = 50) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "untitled"


def _quarantine_corrupt(path: Path) -> None:
    """Best-effort: rename an unparseable store aside so it isn't lost.

    Never raises — quarantine failing must not take the agent down with it.
    """
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path.rename(path.with_name(f"{path.name}.corrupt-{stamp}"))
    except OSError:
        pass


def load_json_store(path: Path, default: Any) -> Any:
    """Load a JSON state file, falling back to `default` if missing/unreadable.

    A file that exists but fails to parse is quarantined (renamed
    "<name>.corrupt-<stamp>") so the next save can't overwrite recoverable data.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        _quarantine_corrupt(path)
        return default


def save_json_store(path: Path, data: Any) -> None:
    """Atomically write a JSON state file (temp file + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

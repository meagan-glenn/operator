"""Tests for the LinkedIn connect governor: flag, cap, dedup, Pacific day boundary."""
import asyncio
import json

from second_me.tools import linkedin


def _check(**args):
    return asyncio.run(linkedin.linkedin_connect_check.handler(args))


def _setup(monkeypatch, tmp_path, *, enabled=True, cap=50, log=None):
    path = tmp_path / "linkedin_connects.json"
    if log is not None:
        path.write_text(json.dumps(log), encoding="utf-8")
    monkeypatch.setattr(linkedin, "LINKEDIN_CONNECTS_FILE", path)
    monkeypatch.setattr(linkedin, "linkedin_connect_enabled", lambda: enabled)
    monkeypatch.setattr(linkedin, "linkedin_daily_cap", lambda: cap)
    monkeypatch.setattr(linkedin, "ensure_dirs", lambda: None)
    return path


def test_disabled_flag_refuses(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, enabled=False)
    res = _check(name="Jane Doe", profile_url="https://linkedin.com/in/jane", icp_fit="CEO, seed SaaS")
    assert res.get("is_error") is True
    assert "OFF" in res["content"][0]["text"]


def test_requires_icp_fit(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = _check(name="Jane Doe", profile_url="https://linkedin.com/in/jane", icp_fit="")
    assert res.get("is_error") is True


def test_approval_logs_and_says_approved_not_sent(monkeypatch, tmp_path):
    path = _setup(monkeypatch, tmp_path, cap=5)
    res = _check(name="Jane Doe", profile_url="https://linkedin.com/in/jane", icp_fit="CEO, seed SaaS")
    text = res["content"][0]["text"]
    assert "is_error" not in res
    assert "APPROVED" in text
    assert "hand this to Meagan" in text
    assert "You do NOT click" in text
    log = json.loads(path.read_text())
    assert len(log) == 1 and log[0]["name"] == "Jane Doe"


def test_dedup_refuses_repeat(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    first = _check(name="Jane Doe", profile_url="https://linkedin.com/in/jane", icp_fit="CEO")
    assert "is_error" not in first
    again = _check(name="Jane Doe", profile_url="https://linkedin.com/in/jane/", icp_fit="CEO")
    assert again.get("is_error") is True
    assert "Already approved" in again["content"][0]["text"]


def test_cap_enforced(monkeypatch, tmp_path):
    from second_me.tools._common import _now

    log = [
        {"name": "A One", "profile_url": "https://x/a", "icp_fit": "f", "at": _now()},
        {"name": "B Two", "profile_url": "https://x/b", "icp_fit": "f", "at": _now()},
    ]
    _setup(monkeypatch, tmp_path, cap=2, log=log)
    res = _check(name="C Three", profile_url="https://x/c", icp_fit="CEO")
    assert res.get("is_error") is True
    assert "Daily cap reached" in res["content"][0]["text"]


def test_cap_counts_pacific_day_not_utc(monkeypatch, tmp_path):
    # Freeze "today" at 2026-06-09 Pacific. An approval at 05:00 UTC on June 9
    # was 22:00 June 8 Pacific (PDT = UTC-7) — it must NOT count toward today.
    # One at 02:00 UTC June 10 was 19:00 June 9 Pacific — it MUST count.
    monkeypatch.setattr(linkedin, "_today_pt", lambda: "2026-06-09")
    log = [
        {"name": "Yesterday Pt", "at": "2026-06-09T05:00:00+00:00"},
        {"name": "Today Pt", "at": "2026-06-10T02:00:00+00:00"},
        {"name": "Bad Stamp", "at": "not-a-date"},
    ]
    assert linkedin._approved_today(log) == 1


def test_status_reports_approved(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, cap=10)
    res = asyncio.run(linkedin.linkedin_connect_status.handler({}))
    assert "approved" in res["content"][0]["text"]

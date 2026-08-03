"""Tests for availability loading (config.py): personal copy wins, degradation is visible.

Pure logic — no network, no SDK client. Guards the pre-publication split: the
committed second_me/availability.json is a generic example; the real schedule
lives in gitignored data/availability.json and must win when present.
"""
import json

import second_me.config as config


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_personal_copy_wins_over_packaged_example(monkeypatch, tmp_path):
    personal = tmp_path / "personal.json"
    packaged = tmp_path / "packaged.json"
    _write(personal, {"timezone": "America/New_York"})
    _write(packaged, {"timezone": "America/Los_Angeles"})
    monkeypatch.setattr(config, "LOCAL_AVAILABILITY_FILE", personal)
    monkeypatch.setattr(config, "AVAILABILITY_FILE", packaged)
    av = config.load_availability()
    assert av["timezone"] == "America/New_York"
    assert config.availability_source().startswith("personal")
    assert config.availability_load_error() is None


def test_falls_back_to_packaged_example_when_no_personal_copy(monkeypatch, tmp_path):
    packaged = tmp_path / "packaged.json"
    _write(packaged, {"timezone": "America/Los_Angeles"})
    monkeypatch.setattr(config, "LOCAL_AVAILABILITY_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(config, "AVAILABILITY_FILE", packaged)
    av = config.load_availability()
    assert av["timezone"] == "America/Los_Angeles"
    assert config.availability_source().startswith("packaged example")


def test_corrupt_personal_copy_uses_defaults_not_example(monkeypatch, tmp_path):
    # A broken personal file must NOT silently fall through to the example —
    # that would swap in the wrong schedule. Defaults + a recorded error instead.
    personal = tmp_path / "personal.json"
    personal.write_text("{not json", encoding="utf-8")
    packaged = tmp_path / "packaged.json"
    _write(packaged, {"timezone": "America/Chicago"})
    monkeypatch.setattr(config, "LOCAL_AVAILABILITY_FILE", personal)
    monkeypatch.setattr(config, "AVAILABILITY_FILE", packaged)
    av = config.load_availability()
    assert av == config._AVAILABILITY_DEFAULTS
    assert config.availability_source() == "built-in defaults"
    assert "personal.json" in config.availability_load_error()


def test_neither_file_present_degrades_to_defaults(monkeypatch, tmp_path):
    # R7: never crash.
    monkeypatch.setattr(config, "LOCAL_AVAILABILITY_FILE", tmp_path / "a.json")
    monkeypatch.setattr(config, "AVAILABILITY_FILE", tmp_path / "b.json")
    av = config.load_availability()
    assert av == config._AVAILABILITY_DEFAULTS
    assert config.availability_source() == "built-in defaults"
    assert config.availability_load_error() is not None


def test_packaged_example_is_generic(monkeypatch):
    # The committed example must stay publishable: no personal emails or
    # personal calendar names.
    text = config.AVAILABILITY_FILE.read_text(encoding="utf-8")
    for leak in ["meagan@", "@justfractional", "@gmail", "@prodfolio", "Family", "WellnessLiving"]:
        assert leak not in text, f"packaged availability example contains personal data: {leak}"
    assert json.loads(text)["google"]["default_booking_account"] == ""

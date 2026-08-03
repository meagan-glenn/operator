"""Tests for the cold-outreach message framework loading (config.py).

Pure logic — no network, no SDK client. Guards the two things that matter:
the packaged default actually ships with the repo, and a vault copy wins
over it (vault = source of truth).
"""
import second_me.config as config


def test_packaged_framework_ships_and_covers_the_channels():
    text = config.OUTREACH_FRAMEWORK_FILE.read_text(encoding="utf-8")
    # The sections the drafting flow leans on. Loose match on purpose — the
    # file is editable prose, but these layers shouldn't silently vanish.
    for needle in [
        "universal skeleton",
        "Email",
        "LinkedIn DM",
        "Connect note",
        "Follow-ups",
        "kill list",
        "Pre-send checklist",
        "swap test",
        "either/or",
    ]:
        assert needle in text, f"framework is missing its '{needle}' section"


def test_load_prefers_vault_copy(monkeypatch, tmp_path):
    vault_copy = tmp_path / "COLD-OUTREACH-FRAMEWORK.md"
    vault_copy.write_text("meagan's own version", encoding="utf-8")
    monkeypatch.setattr(config, "VAULT_OUTREACH_FRAMEWORK_FILE", vault_copy)
    assert config.load_outreach_framework() == "meagan's own version"


def test_load_falls_back_to_packaged_default(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VAULT_OUTREACH_FRAMEWORK_FILE", tmp_path / "missing.md")
    text = config.load_outreach_framework()
    assert "swap test" in text  # the packaged default, not empty


def test_load_degrades_to_empty_not_crash(monkeypatch, tmp_path):
    # R7: neither copy readable -> '' (drafting falls back to the _bdr_block floor).
    monkeypatch.setattr(config, "VAULT_OUTREACH_FRAMEWORK_FILE", tmp_path / "missing.md")
    monkeypatch.setattr(config, "OUTREACH_FRAMEWORK_FILE", tmp_path / "also-missing.md")
    assert config.load_outreach_framework() == ""

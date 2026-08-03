"""Tests for discovery's pure logic: role classify, keys, dedup, vault matching."""
import json

from second_me.tools import discovery


def test_classify_role():
    assert discovery._classify_role("General Partner at Acme Ventures") == "vc"
    assert discovery._classify_role("Principal, Seed Fund") == "vc"
    assert discovery._classify_role("Co-Founder & CEO") == "founder"
    assert discovery._classify_role("Head of Product") == "founder"
    assert discovery._classify_role("Software Engineer") is None
    assert discovery._classify_role("") is None


def test_key_normalizes():
    assert discovery._key(" Jane Doe ", "ACME ") == "jane doe|acme"
    assert discovery._key("Jane", "") == "jane|"


def test_seen_keys_spans_candidates_outreach_and_crm(tmp_path, monkeypatch):
    outreach = tmp_path / "outreach.json"
    outreach.write_text(json.dumps({"targets": [{"name": "Olive Out", "org": "FundX"}]}), encoding="utf-8")
    crm = tmp_path / "crm.json"
    crm.write_text(
        json.dumps({"leads": [{"name": "Carl Crm", "company": "Acme"}], "signals": []}), encoding="utf-8"
    )
    monkeypatch.setattr(discovery, "OUTREACH_FILE", outreach)
    monkeypatch.setattr(discovery, "CRM_FILE", crm)

    db = {"candidates": [{"name": "Cady Cand", "org": "Beta"}]}
    seen = discovery._seen_keys(db)
    assert discovery._key("Cady Cand", "Beta") in seen
    assert discovery._key("Olive Out", "FundX") in seen
    assert discovery._key("Carl Crm", "Acme") in seen
    assert discovery._key("Nobody New", "") not in seen


def test_seen_keys_missing_stores_degrade(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "OUTREACH_FILE", tmp_path / "missing-outreach.json")
    monkeypatch.setattr(discovery, "CRM_FILE", tmp_path / "missing-crm.json")
    assert discovery._seen_keys({"candidates": []}) == set()


def test_known_in_vault_matching(tmp_path, monkeypatch):
    people = tmp_path / "People"
    people.mkdir()
    (people / "Jane Doe.md").write_text("note", encoding="utf-8")
    (people / "Alyssa Smith.md").write_text("note", encoding="utf-8")
    monkeypatch.setattr(discovery, "PEOPLE_DIR", people)
    monkeypatch.setattr(discovery, "vault_available", lambda: True)

    assert discovery._known_in_vault("Jane Doe") is True          # exact stem
    assert discovery._known_in_vault("jane doe") is True          # case-insensitive
    assert discovery._known_in_vault("Jane Doe (Acme)") is True   # whole-word containment
    assert discovery._known_in_vault("Al") is False               # no substring false-positive ("Alyssa")
    assert discovery._known_in_vault("John Doe") is False         # different person, shared surname


def test_known_in_vault_no_vault(monkeypatch):
    monkeypatch.setattr(discovery, "vault_available", lambda: False)
    assert discovery._known_in_vault("Jane Doe") is False


def test_mark_surfaced_flips_only_new():
    batch = [
        {"name": "A", "status": "new"},
        {"name": "B", "status": "surfaced", "surfaced_at": "2026-06-01T00:00:00"},
        {"name": "C", "status": "reviewed"},
        {"name": "D", "status": "new"},
    ]
    assert discovery._mark_surfaced(batch) == 2
    assert batch[0]["status"] == "surfaced" and batch[0]["surfaced_at"]
    assert batch[3]["status"] == "surfaced" and batch[3]["surfaced_at"]
    # already-surfaced keeps its original timestamp; triaged statuses untouched
    assert batch[1]["surfaced_at"] == "2026-06-01T00:00:00"
    assert batch[2]["status"] == "reviewed"


def test_mark_surfaced_empty_batch():
    assert discovery._mark_surfaced([]) == 0


def test_surfaced_is_a_valid_status():
    assert "surfaced" in discovery.CANDIDATE_STATUSES

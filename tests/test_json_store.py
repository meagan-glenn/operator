"""Tests for the shared JSON store helpers (tools/_common.py)."""
import json

from second_me.tools._common import load_json_store, save_json_store


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "store.json"
    data = {"leads": [{"id": "abc", "name": "Jane"}], "signals": []}
    save_json_store(path, data)
    assert load_json_store(path, {}) == data


def test_save_handles_list_default(tmp_path):
    path = tmp_path / "events.json"
    save_json_store(path, [1, 2, 3])
    assert load_json_store(path, []) == [1, 2, 3]


def test_load_missing_returns_default(tmp_path):
    assert load_json_store(tmp_path / "nope.json", {"x": 1}) == {"x": 1}


def test_save_is_atomic_no_temp_left_behind(tmp_path):
    path = tmp_path / "store.json"
    save_json_store(path, {"a": 1})
    save_json_store(path, {"a": 2})
    # Only the real file remains; temp files were replaced into place.
    assert [p.name for p in tmp_path.iterdir()] == ["store.json"]
    assert json.loads(path.read_text()) == {"a": 2}


def test_corrupt_file_quarantined_not_lost(tmp_path):
    path = tmp_path / "store.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_json_store(path, {"fresh": True}) == {"fresh": True}
    # Original file renamed aside, not deleted.
    assert not path.exists()
    corrupt = list(tmp_path.glob("store.json.corrupt-*"))
    assert len(corrupt) == 1
    assert corrupt[0].read_text(encoding="utf-8") == "{not valid json"
    # A subsequent save writes cleanly without clobbering the quarantined copy.
    save_json_store(path, {"fresh": True})
    assert load_json_store(path, {}) == {"fresh": True}
    assert len(list(tmp_path.glob("store.json.corrupt-*"))) == 1

"""
tests/test_settings_store.py
config/settings.json writes: atomic, section-preserving, safe under concurrent writers,
and used by every writer (navigation pins, settings dialog, appearance).
"""
from __future__ import annotations

import json
import threading

import pytest

from utils import settings_store as ss


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_update_keeps_other_sections(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"appearance": {"theme": "dark"}, "rename": {"x": 1}}), encoding="utf-8")
    ss.set_section("navigation", {"pinned": ["C:\\A"]}, f)
    assert _read(f) == {"appearance": {"theme": "dark"}, "rename": {"x": 1}, "navigation": {"pinned": ["C:\\A"]}}


def test_crash_mid_write_leaves_previous_file_intact(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    original = {"appearance": {"theme": "light"}, "navigation": {"pinned": ["keep"]}}
    f.write_text(json.dumps(original), encoding="utf-8")

    def broken_dump(obj, fp, **kw):
        fp.write('{"appearance": {"th')      # partial content, then the process "dies"
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(ss.json, "dump", broken_dump)

    with pytest.raises(RuntimeError):
        ss.set_section("appearance", {"theme": "dark"}, f)
    assert _read(f) == original
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]     # temp file cleaned up


def test_concurrent_writers_do_not_lose_updates(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("{}", encoding="utf-8")
    threads = [threading.Thread(target=ss.set_section, args=(f"k{i}", i, f)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _read(f) == {f"k{i}": i for i in range(24)}


def test_missing_or_corrupt_file_reads_as_empty(tmp_path):
    assert ss.read_settings(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ss.read_settings(bad) == {}


def test_settings_dialog_save_keeps_navigation_pins(tmp_path, monkeypatch):
    import ui.dialogs.settings_dialog as sd
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"navigation": {"pinned": ["C:\\Pinned"]}, "rename": {"collision_digits": 3}}),
                 encoding="utf-8")
    monkeypatch.setattr(sd, "SETTINGS_PATH", f)
    cfg = sd.load_settings()
    cfg["rename"]["collision_digits"] = 4
    cfg.pop("navigation")                    # even a dialog that never saw the pins must not drop them
    assert sd.save_settings(cfg)
    disk = _read(f)
    assert disk["navigation"] == {"pinned": ["C:\\Pinned"]}
    assert disk["rename"]["collision_digits"] == 4


def test_appearance_save_keeps_other_sections(tmp_path, monkeypatch):
    import core.background_manager as bm
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"navigation": {"pinned": ["x"]}}), encoding="utf-8")
    monkeypatch.setattr(bm, "SETTINGS_PATH", f)
    assert bm.save_appearance_settings({"background_mode": "default"})
    assert _read(f) == {"navigation": {"pinned": ["x"]}, "appearance": {"background_mode": "default"}}

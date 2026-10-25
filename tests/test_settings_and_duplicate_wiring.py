"""
tests/test_settings_and_duplicate_wiring.py
Verifies Acceptance Criteria for R3:
- SettingsDialog dinov2_model persistence and restoration
- MainWindow settings wiring (thresholds, batch size, default engine, worker count, tool paths)
- DupManager.find_duplicates_both() fallback on RuntimeError or embedding exceptions
- collect_image_paths() inclusion of VIDEO_EXTS alongside images and RAW
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def suppress_modal_message_boxes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    try:
        import ui.dialogs.settings_dialog as sd
        monkeypatch.setattr(sd.QMessageBox, "information", lambda *args, **kwargs: None)
        monkeypatch.setattr(sd.QMessageBox, "warning", lambda *args, **kwargs: None)
        monkeypatch.setattr(sd.QMessageBox, "critical", lambda *args, **kwargs: None)
    except Exception:
        pass


def test_settings_dialog_preserves_dinov2_model(qapp, tmp_path, monkeypatch):
    from ui.dialogs import settings_dialog as sd

    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.information", lambda *args, **kwargs: None)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", lambda *args, **kwargs: None)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(sd.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(sd.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(sd.QMessageBox, "critical", lambda *args, **kwargs: None)


    custom_cfg = {
        "rename": {
            "default_date_format": "DDMMYY",
            "collision_digits": 3,
            "sanitize_spaces": True,
        },
        "duplicate": {
            "default_engine": "dinov2",
            "phash_threshold": 8,
            "embedding_threshold": 0.90,
            "dinov2_model": "dinov2_vitb14",
            "batch_size": 64,
        },
        "performance": {
            "scanner_workers": 4,
            "use_cuda": False,
        },
        "tools": {
            "exiftool_path": "exiftool.exe",
        },
        "appearance": {
            "background_mode": "default",
        },
    }
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")
    monkeypatch.setattr(sd, "SETTINGS_PATH", cfg_file)

    dlg = sd.SettingsDialog()
    # 0 = dinov2_vits14, 1 = dinov2_vitb14, 2 = dinov2_vitl14
    assert dlg.combo_dino_model.currentIndex() == 1

    # Change to vitl14 and save
    dlg.combo_dino_model.setCurrentIndex(2)
    dlg._save()

    saved_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert saved_data["duplicate"]["dinov2_model"] == "dinov2_vitl14"
    dlg.close()


def test_settings_dialog_default_dinov2_model_fallback(qapp, tmp_path, monkeypatch):
    from ui.dialogs import settings_dialog as sd

    # Config with missing dinov2_model key
    custom_cfg = {
        "duplicate": {
            "default_engine": "phash",
        }
    }
    cfg_file = tmp_path / "settings_default.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")
    monkeypatch.setattr(sd, "SETTINGS_PATH", cfg_file)

    dlg = sd.SettingsDialog()
    assert dlg.combo_dino_model.currentIndex() == 0  # Defaults to dinov2_vits14
    dlg.close()


def test_main_window_wires_settings_from_json(qapp, tmp_path, monkeypatch):
    import ui.dialogs.settings_dialog as sd
    from ui.main_window import MainWindow

    custom_cfg = {
        "duplicate": {
            "default_engine": "both",
            "phash_threshold": 7,
            "embedding_threshold": 0.92,
            "dinov2_model": "dinov2_vitb14",
            "batch_size": 64,
        },
        "performance": {
            "scanner_workers": 12,
            "use_cuda": True,
        },
        "tools": {
            "exiftool_path": "C:\\Tools\\exiftool.exe",
        },
        "appearance": {
            "background_mode": "default",
        },
        "general": {
            "default_directory": str(tmp_path),
        },
    }
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")
    monkeypatch.setattr(sd, "SETTINGS_PATH", cfg_file)

    win = MainWindow()
    try:
        assert win.phash_threshold == 7
        assert win.embedding_threshold == 0.92
        assert win.dinov2_model == "dinov2_vitb14"
        assert win.batch_size == 64
        assert win.scanner_workers == 12
        assert win.exiftool_path == "C:\\Tools\\exiftool.exe"
        # Engine combo index 2 is "Cả hai"
        assert win.dup_preview.engine_combo.currentIndex() == 2
    finally:
        win.close()


def test_main_window_settings_reload(qapp, tmp_path, monkeypatch):
    import ui.dialogs.settings_dialog as sd
    from ui.main_window import MainWindow

    initial_cfg = {
        "duplicate": {
            "default_engine": "phash",
            "phash_threshold": 10,
            "embedding_threshold": 0.95,
            "dinov2_model": "dinov2_vits14",
            "batch_size": 32,
        },
        "performance": {
            "scanner_workers": 4,
        },
        "tools": {
            "exiftool_path": "exiftool.exe",
        },
    }
    cfg_file = tmp_path / "settings_reload.json"
    cfg_file.write_text(json.dumps(initial_cfg), encoding="utf-8")
    monkeypatch.setattr(sd, "SETTINGS_PATH", cfg_file)

    win = MainWindow()
    try:
        assert win.phash_threshold == 10
        assert win.dup_preview.engine_combo.currentIndex() == 0  # phash

        # Simulate update to settings file and reload
        updated_cfg = {
            "duplicate": {
                "default_engine": "dinov2",
                "phash_threshold": 4,
                "embedding_threshold": 0.88,
                "dinov2_model": "dinov2_vitl14",
                "batch_size": 16,
            },
            "performance": {
                "scanner_workers": 24,
            },
            "tools": {
                "exiftool_path": "D:\\custom\\exiftool.exe",
            },
        }
        cfg_file.write_text(json.dumps(updated_cfg), encoding="utf-8")
        win._load_settings()

        assert win.phash_threshold == 4
        assert win.embedding_threshold == 0.88
        assert win.dinov2_model == "dinov2_vitl14"
        assert win.batch_size == 16
        assert win.scanner_workers == 24
        assert win.exiftool_path == "D:\\custom\\exiftool.exe"
        assert win.dup_preview.engine_combo.currentIndex() == 1  # dinov2
    finally:
        win.close()


def test_dup_manager_find_duplicates_both_fallback(monkeypatch):
    from duplicate.dup_manager import DupManager, DupGroup, DupFileItem

    mgr = DupManager(phash_threshold=5)
    dummy_group = [DupGroup(group_id=1, files=[
        DupFileItem(path=Path("img1.jpg"), similarity=1.0, engine="pHash"),
        DupFileItem(path=Path("img2.jpg"), similarity=1.0, engine="pHash"),
    ])]

    monkeypatch.setattr(mgr, "find_duplicates_phash", lambda *args, **kwargs: dummy_group)

    def fail_embed(*args, **kwargs):
        raise RuntimeError("PyTorch not installed. Cannot use EmbeddingEngine.")

    monkeypatch.setattr(mgr, "find_duplicates_embedding", fail_embed)

    # Must return pHash groups without raising RuntimeError
    results = mgr.find_duplicates_both([Path("img1.jpg"), Path("img2.jpg"), Path("img3.jpg")])
    assert len(results) == 1
    assert results[0].files[0].path == Path("img1.jpg")


def test_dup_manager_find_duplicates_both_propagates_cancel(monkeypatch):
    """A user cancel during the DINOv2 stage must not be swallowed as an engine failure."""
    from duplicate.dup_manager import DupManager

    mgr = DupManager()
    monkeypatch.setattr(mgr, "find_duplicates_phash", lambda *args, **kwargs: [])

    def cancelled_embed(*args, **kwargs):
        raise InterruptedError("Đã hủy bởi người dùng")

    monkeypatch.setattr(mgr, "find_duplicates_embedding", cancelled_embed)

    with pytest.raises(InterruptedError):
        mgr.find_duplicates_both([Path("img1.jpg"), Path("img2.jpg")])


def test_collect_image_paths_includes_video_exts(tmp_path):
    from duplicate.dup_manager import collect_image_paths

    (tmp_path / "test.jpg").touch()
    (tmp_path / "test.png").touch()
    (tmp_path / "test.cr2").touch()
    (tmp_path / "test.nef").touch()
    (tmp_path / "test.mp4").touch()
    (tmp_path / "test.mov").touch()
    (tmp_path / "test.mkv").touch()
    (tmp_path / "test.avi").touch()
    (tmp_path / "test.webm").touch()
    (tmp_path / "test.txt").touch()
    (tmp_path / "test.pdf").touch()

    # Subfolder
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "nested.mp4").touch()
    (sub / "nested.jpg").touch()
    (sub / "nested.docx").touch()

    # Non-recursive
    paths_flat = collect_image_paths(tmp_path, recursive=False)
    names_flat = {p.name for p in paths_flat}
    assert "test.jpg" in names_flat
    assert "test.png" in names_flat
    assert "test.cr2" in names_flat
    assert "test.nef" in names_flat
    assert "test.mp4" in names_flat
    assert "test.mov" in names_flat
    assert "test.mkv" in names_flat
    assert "test.avi" in names_flat
    assert "test.webm" in names_flat
    assert "test.txt" not in names_flat
    assert "test.pdf" not in names_flat
    assert "nested.mp4" not in names_flat

    # Recursive
    paths_rec = collect_image_paths(tmp_path, recursive=True)
    names_rec = {p.name for p in paths_rec}
    assert "nested.mp4" in names_rec
    assert "nested.jpg" in names_rec
    assert "nested.docx" not in names_rec

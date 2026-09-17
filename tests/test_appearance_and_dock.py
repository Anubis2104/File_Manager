"""
tests/test_appearance_and_dock.py
Unit tests for:
- core/background_manager.py (settings, internal assets copying, blur)
- ui/widgets/workspace_tabs.py (browser tabs, switching, closing)
- ui/panels/right_dock_panel.py (mode switching, drag-drop slots, numbering)
"""
from __future__ import annotations

import sys
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Ensure QApplication exists for UI tests
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from core.background_manager import (
    load_appearance_settings, save_appearance_settings,
    import_background_file, resolve_background_file,
    apply_acrylic_blur, get_assets_bg_dir,
)
from ui.widgets.workspace_tabs import WorkspaceTabBar, TabItemData
from ui.panels.right_dock_panel import RightDockPanel, QueueDockWidget
from core.scanner import FileInfo


def test_background_manager_copy_and_persist():
    print("[TEST] Running test_background_manager_copy_and_persist...")
    with tempfile.TemporaryDirectory(prefix="bg_test_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        sample_img = tmp_path / "user_sample_wallpaper.jpg"
        sample_img.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"\x00" * 64)

        # 1. Copy into assets/background/
        copied = import_background_file(sample_img)
        assert copied is not None, "Failed to copy background file"
        assert copied.exists(), f"Copied file does not exist: {copied}"
        assert copied.name == "bg_wallpaper.jpg", f"Unexpected filename: {copied.name}"

        # 2. Simulate user deleting original file
        sample_img.unlink()
        assert not sample_img.exists(), "Original file should be deleted"

        # 3. Verify app internal copy still exists and resolves
        resolved = resolve_background_file("assets/background/bg_wallpaper.jpg")
        assert resolved is not None and resolved.exists(), "App should still resolve copied background file!"
        
        # Clean up test artifact from assets/background
        if copied and copied.exists():
            copied.unlink()
        print("  -> Passed: Wallpaper safely preserved in app assets partition even when original is deleted!")


def test_background_settings_save_load():
    print("[TEST] Running test_background_settings_save_load...")
    initial = load_appearance_settings()
    assert isinstance(initial, dict)

    modified = dict(initial)
    modified["blur_enabled"] = True
    modified["background_type"] = "image"
    modified["overlay_opacity"] = 0.75

    ok = save_appearance_settings(modified)
    assert ok, "Failed to save appearance settings"

    reloaded = load_appearance_settings()
    assert reloaded["blur_enabled"] is True
    assert reloaded["background_type"] == "image"
    assert abs(reloaded["overlay_opacity"] - 0.75) < 1e-4

    # Restore initial
    save_appearance_settings(initial)
    print("  -> Passed: Settings save & load verified!")


def test_acrylic_blur_call():
    print("[TEST] Running test_acrylic_blur_call...")
    # Safe invocation test (should return True or False without raising unhandled exception)
    res = apply_acrylic_blur(0, True)
    assert isinstance(res, bool)
    print(f"  -> Passed: apply_acrylic_blur handled gracefully (result={res})")


def test_workspace_tabs():
    print("[TEST] Running test_workspace_tabs...")
    tab_bar = WorkspaceTabBar()
    assert len(tab_bar.tabs) == 0

    # 1. Add tabs
    p1 = Path("/mock/workspace_a")
    p2 = Path("/mock/workspace_b")
    tab_bar.add_tab(p1)
    tab_bar.add_tab(p2)
    assert len(tab_bar.tabs) == 2
    assert tab_bar.active_index == 1
    assert tab_bar.get_active_tab().path == p2

    # 2. Switch tab
    tab_bar.switch_to_tab(0)
    assert tab_bar.active_index == 0
    assert tab_bar.get_active_tab().path == p1

    # 3. Update tab path
    p3 = Path("/mock/workspace_c")
    tab_bar.update_active_tab_path(p3)
    assert tab_bar.get_active_tab().path == p3

    # 4. Cycle tab
    tab_bar.cycle_tab(1)
    assert tab_bar.active_index == 1

    # 5. Close tab
    tab_bar.close_tab(1)
    assert len(tab_bar.tabs) == 1
    assert tab_bar.active_index == 0

    # 6. Closing last tab resets to Home (never leaves zero tabs)
    tab_bar.close_tab(0)
    assert len(tab_bar.tabs) == 1
    assert tab_bar.get_active_tab().path == Path.home()
    print("  -> Passed: WorkspaceTabBar multi-tab management verified!")


def test_right_dock_panel_modes_and_queue():
    print("[TEST] Running test_right_dock_panel_modes_and_queue...")
    dock = RightDockPanel()

    # 1. Default mode is preview
    assert not dock.is_queue_mode(), "Default mode should be preview"
    assert dock.stack.currentIndex() == 0

    # 2. Switch to queue mode
    dock.set_mode("queue")
    assert dock.is_queue_mode(), "Should be in queue mode"
    assert dock.stack.currentIndex() == 1

    # 3. Test queue slots and numbering
    with tempfile.TemporaryDirectory(prefix="dock_test_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "test_a.jpg"
        f2 = tmp_path / "test_b.png"
        f1.write_bytes(b"A" * 100)
        f2.write_bytes(b"B" * 200)

        dock.set_folder(tmp_path)
        dock.open_queue_with_folder(tmp_path, sync=True)

        assert len(dock.queue_dock.queue_items) == 2, f"Expected 2 items, got {len(dock.queue_dock.queue_items)}"

        # Check numbering format
        dock.queue_dock.combo_digits.setCurrentIndex(0) # 3 digits
        seq0 = dock.queue_dock._format_seq(0)
        seq1 = dock.queue_dock._format_seq(1)
        assert seq0 == "001"
        assert seq1 == "002"

        # Check planned name formula [STT]_[Tên cũ]
        table = dock.queue_dock.table
        name0 = table.item(0, 2).text()
        assert name0 == f"001_{dock.queue_dock.queue_items[0].path.name}"

        # Test move item
        dock.queue_dock._move_item(0, 1)
        name0_after = table.item(0, 2).text()
        assert name0_after == f"001_{dock.queue_dock.queue_items[0].path.name}"

        # Test switch back to preview mode
        dock.set_mode("preview")
        assert not dock.is_queue_mode()
        assert dock.stack.currentIndex() == 0

        dock.queue_dock.clear_queue()

    print("  -> Passed: RightDockPanel dual-mode & queue dock operations verified!")


if __name__ == "__main__":
    test_background_manager_copy_and_persist()
    test_background_settings_save_load()
    test_acrylic_blur_call()
    test_workspace_tabs()
    test_right_dock_panel_modes_and_queue()
    print("\nALL APPEARANCE, DOCK & TAB TESTS PASSED (5/5)!")

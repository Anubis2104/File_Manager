"""
tests/test_main_window_integration.py
Test MainWindow initialization and integration with:
- WorkspaceTabBar (Browser-style tabs)
- RightDockPanel (Preview vs Queue dock)
- BackgroundLayer (Wallpaper & acrylic)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from ui.main_window import MainWindow


def test_main_window_components():
    print("[TEST] Initializing MainWindow...")
    win = MainWindow()

    # 1. Check workspace tabs
    assert hasattr(win, "workspace_tabs"), "MainWindow should have workspace_tabs"
    assert len(win.workspace_tabs.tabs) >= 1, "Should have at least 1 tab open"
    print(f"  -> Tab bar verified: {len(win.workspace_tabs.tabs)} tab(s) initialized")

    # 2. Check right dock
    assert hasattr(win, "right_dock"), "MainWindow should have right_dock"
    assert not win.right_dock.is_queue_mode(), "Right dock should start in Preview mode"
    print("  -> Right dock verified: Starts in Preview mode")

    # 3. Check queue rename trigger
    win._open_queue_rename_dialog()
    assert win.right_dock.is_queue_mode(), "Right dock should switch to Queue mode upon trigger"
    print("  -> Queue mode verified: Switched to Queue dock successfully")

    # 4. Switch back to preview
    win.right_dock.set_mode("preview")
    assert not win.right_dock.is_queue_mode()
    print("  -> Preview mode switchback verified")

    # 5. Check background layer
    assert hasattr(win, "bg_layer"), "MainWindow should have bg_layer"
    print("  -> BackgroundLayer verified")

    win.close()
    print("  -> Passed: MainWindow integrated successfully!")


if __name__ == "__main__":
    test_main_window_components()
    print("\nALL MAIN WINDOW INTEGRATION TESTS PASSED!")

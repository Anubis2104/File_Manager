"""
tests/test_polish.py
Phase 9: Explorer shortcuts (Backspace up, Alt+D address, Alt+Enter properties, Share),
accessible names on icon-only buttons, and real glyphs for the new buttons.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

from ui.widgets.command_bar import GLYPH  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    from ui.main_window import MainWindow
    w = MainWindow()
    w.tree_panel._settings_path = tmp_path / "settings.json"
    w.closeEvent = lambda e: e.accept()
    w.show()
    yield w
    w.hide()
    w.deleteLater()


def _wait(pred, ms=3000):
    for _ in range(ms // 20):
        if pred():
            return True
        QTest.qWait(20)
    return pred()


def test_new_glyphs_are_real_icons():
    for key in ("share", "open", "more_options", "properties", "copy_path", "pin"):
        assert len(GLYPH[key]) == 1 and ord(GLYPH[key]) >= 0xE000, key


def test_icon_only_buttons_have_accessible_names(window):
    cb = window.command_bar
    buttons = [b for b in cb.findChildren(QToolButton)
               if not b.objectName().startswith("qt_")]           # Qt's own hidden overflow button
    unnamed = [b.toolTip() for b in buttons if not b.accessibleName()]
    assert unnamed == []


def test_share_button_runs_the_shell_share_verb(window, tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("x")
    window._navigate_to(tmp_path)
    calls = []
    monkeypatch.setattr(window, "_shell_verb", lambda paths, verb: calls.append((paths, verb)))
    model = window.content_panel.model
    _wait(lambda: model.rowCount(model.index(str(tmp_path))) == 1)
    cb = window.command_bar
    window.content_panel.detail_view.clearSelection()
    window._update_command_state()
    assert not cb.btn_share.isEnabled()
    idx = model.index(str(f))
    sel = window.content_panel.detail_view.selectionModel()
    from PyQt6.QtCore import QItemSelectionModel
    sel.select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
    window._update_command_state()
    assert cb.btn_share.isEnabled()
    cb.btn_share.click()
    assert calls == [([f], "windows.share")]


def test_backspace_goes_up_one_level(window, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.txt").write_text("x")          # an empty folder shows the drop zone, not the file view
    window._navigate_to(sub)
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view = window.content_panel.active_view()
    assert _wait(lambda: view.isVisible())
    view.setFocus(Qt.FocusReason.OtherFocusReason)
    assert _wait(lambda: QApplication.focusWidget() is view)
    QTest.keyClick(view, Qt.Key.Key_Backspace)
    assert window.content_panel.current_dir == tmp_path


def test_backspace_still_edits_the_address_box(window, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    window._navigate_to(sub)
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.toolbar.focus_address_bar()
    QApplication.processEvents()
    QTest.keyClick(window.toolbar.address_bar.line_edit, Qt.Key.Key_Backspace)
    assert window.content_panel.current_dir == sub                 # no navigation while typing


def test_alt_d_focuses_the_address_bar(window, tmp_path):
    (tmp_path / "x.txt").write_text("x")
    window._navigate_to(tmp_path)
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view = window.content_panel.active_view()
    assert _wait(lambda: view.isVisible())
    QTest.keyClick(view, Qt.Key.Key_D, Qt.KeyboardModifier.AltModifier)
    assert window.toolbar.address_bar.stack.currentIndex() == 1     # text box mode, like Explorer

"""
tests/test_command_bar.py
Explorer command bar on the real MainWindow (offscreen): layout, Cut/Copy/Paste on the
filesystem, single rename (logged + restorable), delete to Recycle Bin, enable states,
sort, pages, and shortcut scoping.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core.file_ops import invalid_filename_reason  # noqa: E402
from ui import clipboard  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)        # relative rename_log.jsonl lands in tmp, not the repo
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    from ui.main_window import MainWindow
    w = MainWindow()
    w.closeEvent = lambda e: e.accept()
    w.show()
    yield w
    w.hide()
    w.deleteLater()
    QApplication.clipboard().clear()


def _wait(pred, ms=5000):
    for _ in range(ms // 20):
        if pred():
            return True
        QTest.qWait(20)
    return pred()


def _open(window, folder: Path):
    window._navigate_to(folder)
    window.content_panel.set_view("detail")
    model = window.content_panel.model
    _wait(lambda: model.rowCount(model.index(str(folder))) == len(list(folder.iterdir())))


def _select(window, *paths: Path):
    view = window.content_panel.detail_view
    sm = view.selectionModel()
    sm.clearSelection()
    for p in paths:
        idx = window.content_panel.model.index(str(p))
        sm.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    QApplication.processEvents()


def test_layout_matches_explorer(window):
    cb = window.command_bar
    assert window.toolBarArea(cb) == Qt.ToolBarArea.TopToolBarArea
    assert window.toolBarBreak(cb)                       # its own row, under the address row
    assert window.findChild(type(cb), "actionsToolbar") is None
    from PyQt6.QtWidgets import QTabBar
    assert not any(t.isVisible() for t in window.findChildren(QTabBar))   # no page tabs, like Explorer
    tools = [a.text() for a in cb.tools_menu.actions() if not a.isSeparator()]
    assert {"Đổi tên hàng loạt", "Tìm tệp trùng lặp", "Kiểm định & bảo mật"} <= set(tools)


def test_clipboard_round_trip_with_drop_effect(app, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    clipboard.set_files([f], cut=True)
    assert clipboard.read_files() == ([f], True)
    clipboard.set_files([f], cut=False)
    assert clipboard.read_files() == ([f], False)
    clipboard.clear_if_cut([f])                          # copy: keep clipboard
    assert clipboard.has_files()


def test_buttons_follow_selection_and_clipboard(window, tmp_path):
    f = tmp_path / "pic.jpg"
    f.write_bytes(b"1")
    _open(window, tmp_path)
    cb = window.command_bar
    _select(window)
    QApplication.clipboard().clear()
    window._update_command_state()
    assert not cb.btn_copy.isEnabled() and not cb.btn_delete.isEnabled() and not cb.btn_paste.isEnabled()

    _select(window, f)
    assert cb.btn_copy.isEnabled() and cb.btn_cut.isEnabled() and cb.btn_rename.isEnabled()
    window._clipboard_put(cut=False)
    _wait(lambda: cb.btn_paste.isEnabled())
    assert cb.btn_paste.isEnabled()


def test_copy_then_paste_into_another_folder(window, tmp_path):
    src_dir, dst_dir = tmp_path / "src", tmp_path / "dst"
    src_dir.mkdir(); dst_dir.mkdir()
    f = src_dir / "photo.jpg"
    f.write_bytes(b"jpegdata")
    _open(window, src_dir)
    _select(window, f)
    window.command_bar.btn_copy.click()

    _open(window, dst_dir)
    window.last_paste_results = None
    window.command_bar.btn_paste.click()
    assert _wait(lambda: window.last_paste_results is not None)
    assert (dst_dir / "photo.jpg").read_bytes() == b"jpegdata" and f.exists()
    assert clipboard.has_files()                         # copies can be pasted again


def test_cut_then_paste_moves_and_clears_clipboard(window, tmp_path):
    src_dir, dst_dir = tmp_path / "src", tmp_path / "dst"
    src_dir.mkdir(); dst_dir.mkdir()
    f = src_dir / "clip.mp4"
    f.write_bytes(b"v")
    _open(window, src_dir)
    _select(window, f)
    window.command_bar.btn_cut.click()

    _open(window, dst_dir)
    window.last_paste_results = None
    window._paste_from_clipboard()
    assert _wait(lambda: window.last_paste_results is not None)
    assert (dst_dir / "clip.mp4").exists() and not f.exists()
    assert not clipboard.has_files()


def test_single_rename_is_logged_and_restorable(window, tmp_path, monkeypatch):
    import ui.main_window as mw
    f = tmp_path / "IMG_0001.jpg"
    f.write_bytes(b"1")
    _open(window, tmp_path)
    _select(window, f)
    monkeypatch.setattr(mw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Sapa 2026.jpg", True)))
    window.command_bar.btn_rename.click()

    renamed = tmp_path / "Sapa 2026.jpg"
    assert renamed.exists() and not f.exists()
    entry = json.loads((tmp_path / "rename_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["src_path"] == str(f) and entry["dst_path"] == str(renamed)

    from core.logger import RenameLogger
    assert RenameLogger(tmp_path / "rename_log.jsonl").restore_from_log()[0]["success"]
    assert f.exists()


def test_rename_rejects_invalid_names(window, tmp_path, monkeypatch):
    import ui.main_window as mw
    f = tmp_path / "a.txt"
    f.write_text("x")
    _open(window, tmp_path)
    _select(window, f)
    monkeypatch.setattr(mw.QInputDialog, "getText", staticmethod(lambda *a, **k: ("bad:name.txt", True)))
    window._rename_selected()
    assert f.exists() and not (tmp_path / "rename_log.jsonl").exists()


@pytest.mark.parametrize("name,ok", [
    ("photo.jpg", True), ("a:b", False), ("trailing.", False), ("trailing ", False),
    ("CON", False), ("con.txt", False), ("   ", False), ("tab\there", False), ("Ảnh Đà Lạt.png", True),
])
def test_invalid_filename_reason(name, ok):
    assert (invalid_filename_reason(name) == "") is ok


def test_delete_sends_selection_to_recycle_bin(window, tmp_path, monkeypatch):
    import send2trash
    sent = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: sent.append(Path(p)))   # keep the real bin clean
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("1"); b.write_text("2")
    _open(window, tmp_path)
    _select(window, a, b)
    window.command_bar.btn_delete.click()
    assert sorted(sent) == [a, b]


def test_sort_menu_sorts_views(window, tmp_path):
    for n in ("b.txt", "a.txt", "c.txt"):
        (tmp_path / n).write_text(n)
    _open(window, tmp_path)
    window.command_bar.act_descending.trigger()
    header = window.content_panel.detail_view.horizontalHeader()
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    model, root = window.content_panel.model, window.content_panel.detail_view.rootIndex()
    names = [model.fileName(model.index(r, 0, root)) for r in range(model.rowCount(root))]
    assert names == ["c.txt", "b.txt", "a.txt"]


def test_tools_open_pages_and_navigation_returns_to_browser(window, tmp_path):
    window.act_duplicates.trigger()
    assert window.current_page() == 1
    window.act_inspector.trigger()
    assert window.current_page() == 2
    window._navigate_to(tmp_path)
    assert window.current_page() == 0


def test_ctrl_c_in_search_box_copies_text_not_files(window, tmp_path):
    f = tmp_path / "keep.txt"
    f.write_text("x")
    _open(window, tmp_path)
    _select(window, f)
    QApplication.clipboard().clear()
    box = window.toolbar.search_bar
    box.setFocus()
    box.setText("query")
    box.selectAll()
    QTest.keyClick(box, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "query"
    assert not clipboard.has_files()


def test_clear_if_cut_ignores_path_case(app, tmp_path):
    f = tmp_path / "Mixed.TXT"
    f.write_text("x")
    clipboard.set_files([f], cut=True)
    clipboard.clear_if_cut([Path(str(f).upper())])       # same file, different casing
    assert not clipboard.has_files()

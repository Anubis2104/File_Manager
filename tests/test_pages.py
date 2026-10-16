"""
tests/test_pages.py
Duplicates / Inspector as pages beside the navigation pane (like Explorer's Home /
Gallery), on the real MainWindow (offscreen).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ui.panels.tree_panel import ROLE_KIND  # noqa: E402


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
    QApplication.clipboard().clear()


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "Ảnh"
    d.mkdir()
    (d / "a.txt").write_text("a")
    return d


def _wait(pred, ms=3000):
    for _ in range(ms // 20):
        if pred():
            return True
        QTest.qWait(20)
    return pred()


def _open(window, folder: Path):
    window._navigate_to(folder)
    model = window.content_panel.model
    _wait(lambda: model.rowCount(model.index(str(folder))) == 1)


def _select_a(window, folder):
    idx = window.content_panel.model.index(str(folder / "a.txt"))
    view = window.content_panel.active_view()
    view.selectionModel().select(idx, view.selectionModel().SelectionFlag.ClearAndSelect
                                 | view.selectionModel().SelectionFlag.Rows)
    QApplication.processEvents()


def test_navigation_pane_lists_the_pages_after_home(window):
    tree = window.tree_panel.tree
    labels = [tree.topLevelItem(i).text(0) for i in range(4)]
    assert labels[0] == "Trang chủ" and labels[1:3] == ["Trùng lặp", "Kiểm định"]
    assert all(tree.topLevelItem(i).data(0, ROLE_KIND) == "page" for i in (1, 2))


def test_clicking_a_page_keeps_the_navigation_pane(window, folder):
    _open(window, folder)
    item = window.tree_panel.page_items[1]
    window.tree_panel.tree.itemClicked.emit(item, 0)
    assert window.current_page() == 1
    assert window.tree_panel.isVisible()                          # pages sit beside the pane
    assert window.dup_preview.isVisible() and not window.content_panel.isVisible()
    assert window.toolbar.address_bar.crumb_texts() == ["Trùng lặp"]
    assert not window.toolbar.search_box.isEnabled()
    assert window.tree_panel.tree.currentItem() is item


def test_page_has_header(window):
    window._show_page(2)
    holder = window.pages.currentWidget()
    assert holder.header.title.text() == "Kiểm định & bảo mật"
    assert holder.body is window.inspector_panel


def test_back_on_a_page_returns_to_the_same_folder(window, tmp_path, folder):
    other = tmp_path / "Khác"
    other.mkdir()
    _open(window, other)
    _open(window, folder)
    window._show_page(1)
    assert window.toolbar.btn_back.isEnabled()
    window.toolbar.go_back()
    assert window.current_page() == 0
    assert window.content_panel.current_dir == folder              # not the folder before it
    assert window.toolbar.address_bar.crumb_texts()[-1] == folder.name
    assert window.toolbar.search_box.isEnabled()
    window.toolbar.go_back()                                       # now a normal history step
    assert window.content_panel.current_dir == other


def test_leaving_a_page_without_navigating_restores_the_address(window, folder):
    _open(window, folder)
    window._show_page(2)
    window._show_page(0)
    assert window.toolbar.address_bar.crumb_texts()[-1] == folder.name
    assert window.toolbar.page_label is None
    assert window.tree_panel.tree.currentItem() is not window.tree_panel.page_items[2]


def test_file_commands_are_off_on_pages(window, folder):
    from ui import clipboard
    _open(window, folder)
    _select_a(window, folder)
    clipboard.set_files([folder / "a.txt"], cut=False)
    window._update_command_state()
    cb = window.command_bar
    assert cb.btn_copy.isEnabled() and cb.btn_paste.isEnabled() and cb.btn_view.isEnabled()
    window._show_page(1)
    assert not cb.btn_copy.isEnabled() and not cb.btn_delete.isEnabled() and not cb.btn_paste.isEnabled()
    assert not cb.btn_view.isEnabled() and not cb.btn_sort.isEnabled()
    window._show_page(0)
    assert cb.btn_copy.isEnabled() and cb.btn_view.isEnabled()


def test_delete_key_does_nothing_on_a_page(window, folder, monkeypatch):
    import send2trash
    sent = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: sent.append(p))
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    _open(window, folder)
    _select_a(window, folder)
    window._show_page(2)
    QTest.keyClick(window.inspector_panel, Qt.Key.Key_Delete)
    assert sent == [] and (folder / "a.txt").exists()


def test_back_and_forward_walk_the_history(window, tmp_path):
    a, b, c = (tmp_path / n for n in ("a", "b", "c"))
    for d in (a, b, c):
        d.mkdir()
        window._navigate_to(d)
    tb = window.toolbar
    tb.go_back()
    assert window.content_panel.current_dir == b
    tb.go_back()
    assert window.content_panel.current_dir == a
    assert tb.btn_fwd.isEnabled()
    tb.go_forward()
    assert window.content_panel.current_dir == b
    tb.go_forward()
    assert window.content_panel.current_dir == c and not tb.btn_fwd.isEnabled()

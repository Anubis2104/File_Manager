"""
tests/test_context_menu.py
Windows 11 context menu on the real MainWindow (offscreen) and the native Shell menu
(utils/shell_menu.py, real IContextMenu on real temp files; nothing is invoked that
touches the user's clipboard, Recycle Bin or settings).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QItemSelectionModel, QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

from ui import clipboard  # noqa: E402

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows Shell API")


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
    w.tree_panel._settings_path = tmp_path / "settings.json"     # pins never reach the real config
    w.closeEvent = lambda e: e.accept()
    w.show()
    yield w
    w.hide()
    w.deleteLater()
    QApplication.clipboard().clear()


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "data"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("b")
    return d


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
        sm.setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)
    QApplication.processEvents()


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator() and a.text()]


def _submenu(menu: QMenu, title: str) -> QMenu:
    for a in menu.actions():
        if a.menu() is not None and a.text() == title:
            return a.menu()
    raise AssertionError(f"no submenu {title!r} in {_texts(menu)}")


def _action(menu: QMenu, text: str):
    for a in menu.actions():
        if a.text() == text:
            return a
    raise AssertionError(f"no action {text!r} in {_texts(menu)}")


# ── Qt menu structure and routing ──

def test_file_menu_has_quick_row_and_explorer_entries(window, folder):
    _open(window, folder)
    menu = window._build_context_menu([folder / "a.txt"])
    assert list(menu.quick_buttons) == ["cut", "copy", "rename", "share", "delete"]
    assert all(b.accessibleName() for b in menu.quick_buttons.values())
    texts = _texts(menu)
    for t in ("Mở", "Mở bằng...", "Xem trước nhanh", "FileManagerPro", "Sao chép đường dẫn", "Thuộc tính"):
        assert t in texts
    assert texts[-1] == "Hiện thêm tùy chọn"                           # always last, like Win11
    assert _action(menu, "Thuộc tính").shortcut().toString() == "Alt+Enter"
    tools = _texts(_submenu(menu, "FileManagerPro"))
    assert any(t.startswith("Đổi tên hàng loạt") for t in tools)
    assert "Kiểm định tệp này" in tools
    assert "Ghim vào Truy cập nhanh" not in texts                       # files can't be pinned
    menu.deleteLater()


def test_display_shortcuts_do_not_steal_keys(window, folder):
    menu = window._build_context_menu([folder / "a.txt"])
    for a in menu.actions():
        if not a.shortcut().isEmpty():
            assert a.shortcutContext() == Qt.ShortcutContext.WidgetShortcut, a.text()
    menu.deleteLater()


def test_background_menu(window, folder):
    _open(window, folder)
    clipboard.set_files([folder / "a.txt"], cut=False)
    menu = window._build_context_menu([])
    assert list(menu.quick_buttons) == ["paste"]
    texts = _texts(menu)
    for t in ("Xem", "Sắp xếp", "Làm mới", "Mới", "FileManagerPro", "Thuộc tính", "Hiện thêm tùy chọn"):
        assert t in texts
    assert "Mở" not in texts
    assert _texts(_submenu(menu, "Mới")) == ["Thư mục"]
    assert len(_texts(_submenu(menu, "Xem"))) >= 8                     # the 8 layouts
    menu.deleteLater()
    QApplication.clipboard().clear()
    menu = window._build_context_menu([])
    assert "paste" not in menu.quick_buttons                            # nothing to paste
    menu.deleteLater()


def test_new_folder_from_background_menu(window, folder, monkeypatch):
    _open(window, folder)
    monkeypatch.setattr("ui.main_window.QInputDialog.getText",
                        staticmethod(lambda *a, **k: ("Mới tạo", True)), raising=False)
    menu = window._build_context_menu([])
    before = set(folder.iterdir())
    _action(_submenu(menu, "Mới"), "Thư mục").trigger()
    assert _wait(lambda: len(set(folder.iterdir()) - before) == 1)
    assert all(p.is_dir() for p in set(folder.iterdir()) - before)
    menu.deleteLater()


def test_quick_copy_button_puts_files_on_clipboard(window, folder):
    _open(window, folder)
    _select(window, folder / "a.txt", folder / "b.txt")
    menu = window._build_context_menu(window.content_panel.get_selected_paths())
    menu.quick_buttons["copy"].click()
    paths, cut = clipboard.read_files()
    assert sorted(paths) == [folder / "a.txt", folder / "b.txt"] and not cut
    menu.deleteLater()


def test_copy_as_path_quotes_like_explorer(window, folder):
    menu = window._build_context_menu([folder / "a.txt", folder / "sub"])
    _action(menu, "Sao chép đường dẫn").trigger()
    assert QApplication.clipboard().text().splitlines() == [f'"{folder / "a.txt"}"', f'"{folder / "sub"}"']
    menu.deleteLater()


def test_pin_folder_from_menu(window, folder):
    sub = folder / "sub"
    menu = window._build_context_menu([sub])
    _action(menu, "Ghim vào Truy cập nhanh").trigger()
    assert window.tree_panel.is_pinned(sub)
    menu.deleteLater()
    menu = window._build_context_menu([sub])
    _action(menu, "Bỏ ghim khỏi Truy cập nhanh").trigger()
    assert not window.tree_panel.is_pinned(sub)
    menu.deleteLater()


def test_open_folder_navigates_and_open_file_uses_default_app(window, folder, monkeypatch):
    opened = []
    monkeypatch.setattr("ui.main_window.os.startfile", lambda p: opened.append(p), raising=False)
    _open(window, folder)
    menu = window._build_context_menu([folder / "a.txt"])
    _action(menu, "Mở").trigger()
    assert opened == [str(folder / "a.txt")]
    menu.deleteLater()
    menu = window._build_context_menu([folder / "sub"])
    _action(menu, "Mở").trigger()
    assert _wait(lambda: window.content_panel.current_dir == folder / "sub")
    menu.deleteLater()


def test_double_click_file_opens_it(window, folder, monkeypatch):
    opened = []
    monkeypatch.setattr("ui.main_window.os.startfile", lambda p: opened.append(p), raising=False)
    _open(window, folder)
    idx = window.content_panel.model.index(str(folder / "b.txt"))
    window.content_panel.detail_view.activated.emit(idx)
    assert opened == [str(folder / "b.txt")]


def test_shift_right_click_opens_native_menu(window, folder, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_show_shell_menu", lambda paths: calls.append(paths))
    monkeypatch.setattr(QApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.KeyboardModifier.ShiftModifier))
    window._show_content_context_menu(QPoint(10, 10), [folder / "a.txt"])
    assert calls == [[folder / "a.txt"]]


def test_shell_menu_rename_is_handled_by_the_app(window, folder, monkeypatch):
    """The Shell hands 'rename' back to the host view; the app must start its own rename."""
    if sys.platform != "win32":
        pytest.skip("Windows Shell API")
    import utils.shell_menu as sm
    renamed, refreshed = [], []
    monkeypatch.setattr(sm.ShellContextMenu, "show", lambda self, x, y: "rename")
    monkeypatch.setattr(window, "_rename_selected", lambda: renamed.append(True))
    monkeypatch.setattr(window, "_refresh", lambda: refreshed.append(True))
    _open(window, folder)
    window._show_shell_menu([folder / "a.txt"])
    assert renamed == [True] and refreshed == [True]


def test_shift_f10_and_alt_enter_are_scoped_to_file_views(window, folder, monkeypatch):
    shell, props = [], []
    monkeypatch.setattr(window, "_show_shell_menu", lambda paths: shell.append(paths))
    monkeypatch.setattr(window, "_shell_verb", lambda paths, verb: props.append((paths, verb)))
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    _open(window, folder)
    _select(window, folder / "a.txt")
    view = window.content_panel.detail_view
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(view, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
    assert shell == [[folder / "a.txt"]]
    assert props == [([folder / "a.txt"], "properties")]
    view.clearSelection()
    QTest.keyClick(view, Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
    assert props[-1] == ([folder], "properties")                         # nothing selected: the folder


def test_right_click_on_empty_space_drops_selection(window, folder, monkeypatch):
    import ui.panels.content_panel as cp
    got = []
    window.content_panel.context_menu_requested.disconnect()
    window.content_panel.context_menu_requested.connect(lambda pos, sel: got.append(sel))
    _open(window, folder)
    _select(window, folder / "a.txt")
    view = window.content_panel.detail_view
    empty = QPoint(5, view.viewport().height() - 3)
    assert not view.indexAt(empty).isValid()
    # keyboard Menu key (cursor elsewhere): keep the selection
    monkeypatch.setattr(cp.QCursor, "pos", staticmethod(lambda: view.viewport().mapToGlobal(QPoint(-50, -50))))
    window.content_panel._on_context_menu(empty)
    assert got[-1] == [folder / "a.txt"]
    # mouse right-click on empty space: background menu, selection cleared
    monkeypatch.setattr(cp.QCursor, "pos", staticmethod(lambda: view.viewport().mapToGlobal(empty)))
    window.content_panel._on_context_menu(empty)
    assert got[-1] == [] and window.content_panel.get_selected_paths() == []


@windows_only
def test_native_event_forwards_owner_draw_messages_to_open_shell_menu(window, monkeypatch):
    import ctypes
    from ctypes import wintypes
    import utils.shell_menu as sm

    class FakeMenu:
        def handle_menu_message(self, msg, wparam, lparam):
            return 7 if (msg, wparam, lparam) == (sm.WM_INITMENUPOPUP, 11, 22) else None

    msg = wintypes.MSG()
    msg.message, msg.wParam, msg.lParam = sm.WM_INITMENUPOPUP, 11, 22
    addr = ctypes.addressof(msg)
    assert window.nativeEvent(b"windows_generic_MSG", addr) == (False, 0)   # no menu open
    monkeypatch.setattr(sm, "_active", FakeMenu())
    assert window.nativeEvent(b"windows_generic_MSG", addr) == (True, 7)
    msg.message = 0x0200                                                   # WM_MOUSEMOVE: not forwarded
    assert window.nativeEvent(b"windows_generic_MSG", addr) == (False, 0)


# ── Native Shell menu (real IContextMenu) ──

@windows_only
def test_shell_menu_for_files_has_explorer_verbs(folder):
    from utils.shell_menu import ShellContextMenu
    with ShellContextMenu([folder / "a.txt", folder / "b.txt"]) as m:
        assert m.item_count() > 5
        assert {"open", "copy", "cut", "delete", "properties"} <= m.verbs()


@windows_only
def test_shell_menu_for_folder_background(folder):
    from utils.shell_menu import ShellContextMenu
    with ShellContextMenu([folder], background=True) as m:
        verbs = m.verbs()
    assert "properties" in verbs
    assert "open" not in verbs and "delete" not in verbs                 # it's the folder's inside


@windows_only
def test_shell_menu_rejects_mixed_parents(tmp_path, folder):
    from utils.shell_menu import ShellContextMenu
    other = tmp_path / "other.txt"
    other.write_text("x")
    with pytest.raises((OSError, ValueError)):
        ShellContextMenu([folder / "a.txt", other])


@windows_only
def test_shell_menu_handles_unicode_paths(tmp_path):
    from utils.shell_menu import ShellContextMenu
    d = tmp_path / "Ảnh đẹp 😀"
    d.mkdir()
    f = d / "tệp mẫu.txt"
    f.write_text("x", encoding="utf-8")
    with ShellContextMenu([f]) as m:
        assert "properties" in m.verbs()

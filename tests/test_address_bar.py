"""
tests/test_address_bar.py
Explorer address row (ui/widgets/toolbar.py): breadcrumbs, subfolder menus, overflow,
text-edit mode, search placeholder, refresh and history buttons.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QSignalSpy, QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui.widgets.toolbar import AppToolBar, BreadcrumbAddressBar, THIS_PC  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    from ui.theme import theme
    if theme()._app is None:
        theme().install(a, mode="dark")
    return a


@pytest.fixture
def make(app):
    """Create parentless widgets and delete them before the next test (as qtbot.addWidget does):
    leftovers destroyed after QApplication at interpreter exit crash the test process."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    created = []

    def factory(cls):
        w = cls()
        created.append(w)
        return w
    yield factory
    for w in created:
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    import ui.shell
    monkeypatch.setattr(ui.shell, "explorer_shows_hidden", lambda: False)   # Explorer defaults
    monkeypatch.setattr(ui.shell, "explorer_shows_protected_os_files", lambda: False)
    base = tmp_path / "Photos"
    for name in ("2024", "2025", "Album B", "album a", ".gradle", "secret"):
        (base / name).mkdir(parents=True)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(base / "secret"), 0x2)   # FILE_ATTRIBUTE_HIDDEN
    else:
        (base / "secret").rename(base / ".secret")
    (base / "not_a_dir.jpg").write_bytes(b"x")
    return base


def test_breadcrumbs_start_at_this_pc_with_drive_label(make, tree):
    bar = make(BreadcrumbAddressBar)
    bar.set_path(tree)
    texts = bar.crumb_texts()
    assert texts[0] == THIS_PC
    drive = tree.anchor.rstrip("\\/")
    assert texts[1].endswith(f"({drive})")            # "Local Disk (C:)" / "<label> (D:)"
    assert texts[-1] == "Photos"
    assert texts[2:] == list(tree.parts[1:])


def test_clicking_a_crumb_navigates_to_that_folder(make, tree):
    bar = make(BreadcrumbAddressBar)
    bar.set_path(tree / "2024")
    spy = QSignalSpy(bar.navigate_requested)
    crumb, _ = bar._segments[-2]                       # "Photos"
    crumb.click()
    assert len(spy) == 1 and spy[0][0] == tree


def test_chevron_menu_lists_visible_subfolders_sorted(make, tree):
    bar = make(BreadcrumbAddressBar)
    bar.set_path(tree)
    menu = bar._children_menu(tree)
    names = [a.text() for a in menu.actions()]
    # Like Explorer on Windows: a leading dot doesn't hide ".gradle"; the Hidden attribute does
    assert names == [".gradle", "2024", "2025", "album a", "Album B"]

    spy = QSignalSpy(bar.navigate_requested)
    menu.actions()[2].trigger()
    assert spy[0][0] == tree / "2025"


def test_empty_folder_menu_has_disabled_placeholder(make, tree):
    bar = make(BreadcrumbAddressBar)
    actions = bar._children_menu(tree / "2024").actions()
    assert len(actions) == 1 and not actions[0].isEnabled()


def test_long_path_collapses_leading_crumbs_into_overflow_menu(make, tmp_path):
    deep = tmp_path.joinpath(*[f"Thu muc cap {i} dai" for i in range(6)])   # < MAX_PATH
    deep.mkdir(parents=True)
    bar = make(BreadcrumbAddressBar)
    bar.resize(420, 32)
    bar.show()
    bar.set_path(deep)
    QApplication.processEvents()

    assert bar.hidden_crumb_count() > 0
    assert bar.btn_overflow.isVisible()
    hidden = [c.text() for c, _ in bar._segments if c.isHidden()]
    assert [a.text() for a in bar.btn_overflow.menu().actions()] == hidden[::-1]
    assert not bar._segments[-1][0].isHidden()        # current folder always visible

    bar.resize(4000, 32)
    QApplication.processEvents()
    assert bar.hidden_crumb_count() == 0 and not bar.btn_overflow.isVisible()


def test_edit_mode_navigates_on_enter_and_rejects_invalid_path(make, tree):
    bar = make(BreadcrumbAddressBar)
    bar.show()
    bar.set_path(tree)
    bar.focus_edit()
    assert bar.stack.currentIndex() == 1
    assert bar.line_edit.text() == str(tree)

    spy = QSignalSpy(bar.navigate_requested)
    bar.line_edit.setText(str(tree / "2025"))
    QTest.keyClick(bar.line_edit, Qt.Key.Key_Return)
    assert spy[0][0] == tree / "2025" and bar.stack.currentIndex() == 0

    bar.focus_edit()
    bar.line_edit.setText(str(tree / "does-not-exist"))
    QTest.keyClick(bar.line_edit, Qt.Key.Key_Return)
    assert bar.line_edit.property("invalid") is True and len(spy) == 1

    QTest.keyClick(bar.line_edit, Qt.Key.Key_Escape)
    assert bar.stack.currentIndex() == 0
    assert bar.line_edit.text() == str(tree / "2025")   # edit discarded


def test_toolbar_search_placeholder_refresh_and_history(make, tree):
    tb = make(AppToolBar)
    tb.push_path(tree)
    assert tb.search_bar.placeholderText() == "Tìm trong Photos"
    assert not tb.btn_back.isEnabled() and tb.btn_up.isEnabled()

    refresh = QSignalSpy(tb.refresh_requested)
    tb.btn_refresh.click()
    assert len(refresh) == 1

    tb.push_path(tree / "2024")
    nav = QSignalSpy(tb.navigate_requested)
    tb.btn_back.click()
    assert nav[0][0] == tree and tb.btn_fwd.isEnabled()
    assert tb.address_bar.crumb_texts()[-1] == "Photos"

    root = Path(tree.anchor)
    tb.push_path(root)
    assert not tb.btn_up.isEnabled()                  # nothing above a drive root
    assert tb.search_bar.placeholderText().startswith("Tìm trong ")
    assert tb.search_bar.placeholderText().endswith(f"({root.drive})")

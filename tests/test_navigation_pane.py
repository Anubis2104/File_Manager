"""
tests/test_navigation_pane.py
Explorer navigation pane (ui/panels/tree_panel.py): sections, Quick access pins saved
to a (temporary) settings file, lazy folder loading with Explorer's hidden rules,
and selection sync without navigation loops.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PyQt6.QtTest import QSignalSpy  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTreeWidgetItem  # noqa: E402

from ui.panels.tree_panel import ROLE_KIND, ROLE_PATH, TreePanel  # noqa: E402
from ui.shell import known_folders  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    from ui.theme import theme
    if theme()._app is None:
        theme().install(a, mode="dark")
    return a


@pytest.fixture
def pane(app, tmp_path, monkeypatch):
    import ui.shell
    monkeypatch.setattr(ui.shell, "explorer_shows_hidden", lambda: False)        # Explorer defaults,
    monkeypatch.setattr(ui.shell, "explorer_shows_protected_os_files", lambda: False)   # whatever this PC uses
    settings = tmp_path / "settings.json"            # never the real config/settings.json
    p = TreePanel(settings_path=settings)
    yield p
    p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _top(pane):
    t = pane.tree
    return [t.topLevelItem(i) for i in range(t.topLevelItemCount())]


def _labels(items):
    return [i.text(0) if i.data(0, ROLE_KIND) != "separator" else "---" for i in items]


def test_sections_match_explorer(pane):
    labels = _labels(_top(pane))
    assert labels[0] == "Trang chủ"
    assert labels[-1] == "This PC"
    assert labels.count("---") == 2
    first_sep, second_sep = [i for i, l in enumerate(labels) if l == "---"]
    pinned = labels[first_sep + 1:second_sep]
    assert pinned == [label for label, _ in known_folders()]          # Explorer's default pins
    assert all(i.data(0, ROLE_KIND) == "pinned" for i in _top(pane)[first_sep + 1:second_sep])


def test_this_pc_lists_drives_with_explorer_labels(pane):
    pc = pane.this_pc
    assert pc.isExpanded() and pc.childCount() >= 1
    drives = [pc.child(i).text(0) for i in range(pc.childCount())]
    sys_drive = Path.home().anchor.rstrip("\\/")
    assert any(d.endswith(f"({sys_drive})") for d in drives), drives


def test_clicking_a_pin_navigates(pane):
    spy = QSignalSpy(pane.folder_selected)
    item = next(i for i in _top(pane) if i.data(0, ROLE_KIND) == "pinned")
    pane._on_item_clicked(item)
    assert spy[0][0] == item.data(0, ROLE_PATH)


def test_lazy_children_follow_explorer_hidden_rules(pane, tmp_path):
    root = tmp_path / "Lib"
    for name in (".gradle", "Photos", "secret"):
        (root / name).mkdir(parents=True)
    (root / "Photos" / "2026").mkdir()
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(root / "secret"), 0x2)
    else:
        (root / "secret").rename(root / ".secret")
    item = pane._add_folder(None, "Lib", root)
    assert item.childCount() == 0                                     # nothing listed until expanded
    item.setExpanded(True)
    names = [item.child(i).text(0) for i in range(item.childCount())]
    assert names == [".gradle", "Photos"]
    photos, gradle = item.child(1), item.child(0)
    # Chevrons are optimistic (no scan per child); an empty folder loses it once opened
    show = QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
    assert photos.childIndicatorPolicy() == show and gradle.childIndicatorPolicy() == show
    gradle.setExpanded(True)
    assert gradle.childIndicatorPolicy() == QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
    photos.setExpanded(True)
    assert photos.childCount() == 1 and photos.child(0).text(0) == "2026"


def test_pin_keeps_expanded_nodes(pane, tmp_path):
    deep = tmp_path / "x" / "y"
    deep.mkdir(parents=True)
    pane.expand_to_open_folder = True
    pane.expand_to(deep)
    before = [str(p) for p in pane._expanded_paths()]
    pane.pin(tmp_path / "x")
    assert [str(p) for p in pane._expanded_paths()] == before


def test_default_does_not_unfold_tree_to_open_folder(pane, tmp_path):
    """Windows 11 default: 'Expand to open folder' is off."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    pane.expand_to_open_folder = False
    pane.expand_to(deep)
    assert pane.get_selected_path() is None
    drives = [pane.this_pc.child(i) for i in range(pane.this_pc.childCount())]
    assert not any(d.isExpanded() for d in drives)


def test_expand_to_open_folder_selects_node_under_this_pc_without_navigating(pane, tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    pane.expand_to_open_folder = True
    spy = QSignalSpy(pane.folder_selected)
    pane.expand_to(deep)
    assert pane.get_selected_path() == deep
    assert len(spy) == 0                                              # sync must not loop into navigation
    chain, node = [], pane.tree.currentItem()
    while node is not None:
        chain.append(node)
        node = node.parent()
    assert chain[-1] is pane.this_pc


def test_expand_to_prefers_pinned_entry(pane):
    label, path = known_folders()[0]
    pane.expand_to(path)
    cur = pane.tree.currentItem()
    assert cur.data(0, ROLE_KIND) == "pinned" and cur.text(0) == label


def test_pin_and_unpin_persist(pane, tmp_path):
    folder = tmp_path / "Projects"
    folder.mkdir()
    assert not pane.is_pinned(folder)
    pane.pin(folder)
    assert pane.is_pinned(folder)
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert str(folder) in saved["navigation"]["pinned"]
    assert "Projects" in _labels(_top(pane))

    pane.unpin(folder)
    assert not pane.is_pinned(folder)
    assert "Projects" not in _labels(_top(pane))


def test_pins_keep_other_settings(pane, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"appearance": {"theme": "dark"}}), encoding="utf-8")
    pane.pin(tmp_path)
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["appearance"] == {"theme": "dark"} and saved["navigation"]["pinned"]

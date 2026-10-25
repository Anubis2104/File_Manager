"""
ui/panels/tree_panel.py
Explorer navigation pane:

    Trang chủ                 (the user's profile folder)
    Trùng lặp / Kiểm định     FileManagerPro's pages (like Explorer's Gallery)
  > OneDrive
  ───────────
    Desktop            📌     Quick access pins (Explorer's defaults; pin / unpin via
    Downloads          📌     the context menu, saved in config/settings.json)
    ...
  ───────────
  v This PC
    > Local Disk (C:)          drives; subfolders load when a node is expanded

Hidden folders follow Explorer's own "Show hidden items" setting. The public API of
the previous tree (folder_selected, folder_context_menu_requested, get_selected_path,
expand_to) is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ui.shell import (
    computer_icon, drive_display_name, explorer_expands_to_current_folder, glyph_font, has_subfolder,
    known_folders, list_drives, onedrive_root, shell_icon, subfolders,
)
from ui.theme import qcolor, style

ROLE_PATH = Qt.ItemDataRole.UserRole           # Path of a folder item (None for "This PC")
ROLE_KIND = Qt.ItemDataRole.UserRole + 1       # "folder" | "pinned" | "separator" | "computer" | "page"
ROLE_LOADED = Qt.ItemDataRole.UserRole + 2     # children already listed
ROLE_PAGE = Qt.ItemDataRole.UserRole + 3       # main-window page index of a "page" item
PAGES = ((1, "Trùng lặp", "\uE8C8", "Tìm và dọn tệp trùng lặp"),
         (2, "Kiểm định", "\uEA18", "Kiểm định byte, overlay và mã độc"))
GLYPH_PIN = ""
ROW_HEIGHT = 26                                 # Explorer: 32 physical px at 125%
MAX_CHILDREN = 2000


def _settings_file() -> Path:
    from utils.settings_store import default_path
    return default_path()


class _NavDelegate(QStyledItemDelegate):
    """Draws section separators and the pin glyph on Quick access items."""

    def sizeHint(self, option, index):
        if index.data(ROLE_KIND) == "separator":
            return QSize(option.rect.width(), 9)
        return QSize(super().sizeHint(option, index).width(), ROW_HEIGHT)

    def paint(self, painter, option, index):
        kind = index.data(ROLE_KIND)
        if kind == "separator":
            painter.save()
            painter.setPen(qcolor("stroke_control"))
            y = option.rect.center().y()
            painter.drawLine(option.rect.left() + 4, y, option.rect.right() - 8, y)
            painter.restore()
            return
        super().paint(painter, option, index)
        if kind == "pinned":
            painter.save()
            painter.setFont(glyph_font(10))
            painter.setPen(qcolor("text_tertiary"))
            r = option.rect
            painter.drawText(QRect(r.right() - 24, r.top(), 18, r.height()), Qt.AlignmentFlag.AlignCenter, GLYPH_PIN)
            painter.restore()


class TreePanel(QWidget):
    """Explorer-style navigation pane. Emits `folder_selected` on click."""

    folder_selected = pyqtSignal(Path)
    page_selected = pyqtSignal(int)                            # PAGES index (1 = duplicates, 2 = inspector)
    folder_context_menu_requested = pyqtSignal(object, Path)  # (global_pos, folder_path)

    def __init__(self, parent=None, settings_path: Optional[Path] = None):
        super().__init__(parent)
        self._settings_path = settings_path
        self._syncing = False
        # Explorer's "Expand to open folder" (off by default): when off, navigating only
        # highlights a matching pin / an already-open node instead of unfolding the tree
        self.expand_to_open_folder = explorer_expands_to_current_folder()
        self._build_ui()
        self.reload()

    # ── construction ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navigationPane")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(False)          # separators are shorter
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setItemDelegate(_NavDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemActivated.connect(self._on_item_clicked)
        style(self.tree, "#navigationPane { padding-left: 4px; }")
        layout.addWidget(self.tree)

    def reload(self):
        self.tree.clear()
        home = Path.home()
        self._add_folder(None, "Trang chủ", home, kind="folder", expandable=False)
        from ui.widgets.command_bar import glyph_icon
        self.page_items: dict[int, QTreeWidgetItem] = {}
        for index, label, glyph, tip in PAGES:
            item = QTreeWidgetItem([label])
            item.setIcon(0, glyph_icon(glyph))
            item.setToolTip(0, tip)
            item.setData(0, ROLE_KIND, "page")
            item.setData(0, ROLE_PAGE, index)
            item.setData(0, ROLE_PATH, None)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            self.tree.addTopLevelItem(item)
            self.page_items[index] = item
        od = onedrive_root()
        if od is not None:
            # Personal OneDrive folder is just "OneDrive"; Explorer labels it "... - Personal"
            label = "OneDrive - Personal" if od.name == "OneDrive" else od.name
            self._add_folder(None, label, od, expandable=has_subfolder(od))
        self._add_separator()
        self._pinned_items: list[QTreeWidgetItem] = []
        for path in self.pinned_paths():
            self._pinned_items.append(self._add_folder(None, self._label_for(path), path,
                                                       kind="pinned", expandable=False))
        self._add_separator()
        self.this_pc = QTreeWidgetItem(["This PC"])
        self.this_pc.setIcon(0, computer_icon())
        self.this_pc.setData(0, ROLE_KIND, "computer")
        self.this_pc.setData(0, ROLE_PATH, None)
        self.this_pc.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        self.tree.addTopLevelItem(self.this_pc)
        self.this_pc.setExpanded(True)

    def _add_separator(self):
        sep = QTreeWidgetItem()
        sep.setData(0, ROLE_KIND, "separator")
        sep.setFlags(Qt.ItemFlag.NoItemFlags)
        self.tree.addTopLevelItem(sep)

    def _add_folder(self, parent: Optional[QTreeWidgetItem], label: str, path: Path,
                    kind: str = "folder", expandable: Optional[bool] = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setIcon(0, shell_icon(path))
        item.setToolTip(0, str(path))
        item.setData(0, ROLE_PATH, path)
        item.setData(0, ROLE_KIND, kind)
        if expandable is None:
            # Like Explorer on slow drives: assume expandable instead of scanning every child
            # (one scandir per child froze the pane on big / OneDrive / network folders);
            # _load_children hides the chevron when the folder turns out to be empty.
            expandable = True
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator if expandable
            else QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    @staticmethod
    def _label_for(path: Path) -> str:
        for label, p in known_folders():
            if p == path:
                return label
        return path.name or str(path)

    # ── lazy loading ─────────────────────────────────────────────

    def _on_expanded(self, item: QTreeWidgetItem):
        self._load_children(item)

    def _load_children(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_LOADED):
            return
        item.setData(0, ROLE_LOADED, True)
        if item.data(0, ROLE_KIND) == "computer":
            for root in list_drives():
                self._add_folder(item, drive_display_name(root), root, expandable=True)
            return
        path: Path = item.data(0, ROLE_PATH)
        children = subfolders(path, limit=MAX_CHILDREN)
        for child in children:
            self._add_folder(item, child.name, child)
        if not children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

    # ── selection / navigation ───────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int = 0):
        if self._syncing:
            return
        path = item.data(0, ROLE_PATH)
        if item.data(0, ROLE_KIND) == "page":
            self.page_selected.emit(int(item.data(0, ROLE_PAGE)))
        elif path is not None and Path(path).is_dir():
            self.folder_selected.emit(Path(path))
        elif item.data(0, ROLE_KIND) == "computer":
            item.setExpanded(not item.isExpanded())

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        path = item.data(0, ROLE_PATH)
        if path is not None and Path(path).is_dir():
            self.folder_context_menu_requested.emit(self.tree.viewport().mapToGlobal(pos), Path(path))

    def select_page(self, index: int):
        """Highlight a page entry (the window switched pages some other way)."""
        item = self.page_items.get(index)
        if item is None:
            return
        self._syncing = True
        try:
            self.tree.setCurrentItem(item)
        finally:
            self._syncing = False

    def get_selected_path(self) -> Optional[Path]:
        item = self.tree.currentItem()
        path = item.data(0, ROLE_PATH) if item is not None else None
        return Path(path) if path is not None and Path(path).is_dir() else None

    def expand_to(self, path: Path):
        """Select `path`: a matching pin/Home entry, else its node under This PC (unfolding
        the tree only when 'Expand to open folder' is on, as in Explorer)."""
        path = Path(path)
        self._syncing = True
        try:
            target = self._find_top_level(path) or self._find_under_this_pc(path, unfold=self.expand_to_open_folder)
            if target is not None:
                self.tree.setCurrentItem(target)
                self.tree.scrollToItem(target)
            else:
                self.tree.clearSelection()
                self.tree.setCurrentIndex(QModelIndex())     # no stale highlight (e.g. a page entry)
        finally:
            self._syncing = False

    def _find_top_level(self, path: Path) -> Optional[QTreeWidgetItem]:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            p = item.data(0, ROLE_PATH)
            if p is not None and _same(Path(p), path):
                return item
        return None

    def _find_under_this_pc(self, path: Path, unfold: bool) -> Optional[QTreeWidgetItem]:
        """Walk This PC > drive > ... to `path`. Without `unfold`, only already-listed and
        expanded nodes are followed and an exact match is required."""
        node = self.this_pc
        self._load_children(node)
        parts = path.parts
        if not parts:
            return None
        acc = Path(parts[0])
        node = self._child_with_path(node, acc)
        for part in parts[1:]:
            if node is None:
                return None
            if unfold:
                self._load_children(node)
                node.setExpanded(True)
            elif not (node.data(0, ROLE_LOADED) and node.isExpanded()):
                return None
            acc = acc / part
            nxt = self._child_with_path(node, acc)
            if nxt is None:                  # hidden or beyond MAX_CHILDREN
                if unfold and acc.is_dir():
                    nxt = self._add_folder(node, acc.name or str(acc), acc)
                else:
                    return node if unfold else None
            node = nxt
        return node

    @staticmethod
    def _child_with_path(node: QTreeWidgetItem, path: Path) -> Optional[QTreeWidgetItem]:
        for i in range(node.childCount()):
            child = node.child(i)
            p = child.data(0, ROLE_PATH)
            if p is not None and _same(Path(p), path):
                return child
        return None

    # ── Quick access pins ────────────────────────────────────────

    def pinned_paths(self) -> list[Path]:
        saved = self._read_settings().get("navigation", {}).get("pinned")
        if saved is None:
            return [p for _, p in known_folders()]
        return [Path(p) for p in saved if Path(p).is_dir()]

    def is_pinned(self, path: Path) -> bool:
        return any(_same(p, path) for p in self.pinned_paths())

    def pin(self, path: Path):
        pins = self.pinned_paths()
        if not any(_same(p, path) for p in pins):
            pins.append(Path(path))
            self._save_pins(pins)

    def unpin(self, path: Path):
        self._save_pins([p for p in self.pinned_paths() if not _same(p, path)])

    def _save_pins(self, pins: list[Path]):
        from utils.settings_store import update_settings
        update_settings(lambda cfg: cfg.setdefault("navigation", {}).__setitem__("pinned", [str(p) for p in pins]),
                        self._settings_path or _settings_file())
        current = self.get_selected_path()
        expanded = self._expanded_paths()
        self.reload()
        self._restore_expanded(expanded)
        if current is not None:
            self.expand_to(current)

    def _expanded_paths(self) -> list[Path]:
        """Expanded folder nodes under This PC, parents first."""
        out: list[Path] = []

        def walk(node: QTreeWidgetItem):
            for i in range(node.childCount()):
                child = node.child(i)
                if child.isExpanded() and child.data(0, ROLE_PATH) is not None:
                    out.append(Path(child.data(0, ROLE_PATH)))
                    walk(child)
        walk(self.this_pc)
        return out

    def _restore_expanded(self, paths: list[Path]):
        for path in paths:
            node = self._find_under_this_pc(path, unfold=False)
            if node is None:                         # parent chain expanded first, so load step by step
                parent = self._find_under_this_pc(path.parent, unfold=False) if path.parent != path else None
                if parent is not None:
                    self._load_children(parent)
                    node = self._child_with_path(parent, path)
            if node is not None:
                self._load_children(node)
                node.setExpanded(True)

    def _read_settings(self) -> dict:
        from utils.settings_store import read_settings
        return read_settings(self._settings_path or _settings_file())


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))

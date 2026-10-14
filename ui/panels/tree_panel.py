"""
ui/panels/tree_panel.py
Left sidebar: directory tree view (QTreeView + QFileSystemModel).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QDir, pyqtSignal, QSortFilterProxyModel, QModelIndex
from PyQt6.QtGui  import QFileSystemModel, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeView, QLabel,
    QHBoxLayout, QToolButton, QSizePolicy,
)
from ui.theme import style


class TreePanel(QWidget):
    """Displays folder hierarchy. Emits `folder_selected` on click."""

    folder_selected = pyqtSignal(Path)
    folder_context_menu_requested = pyqtSignal(object, Path)  # (global_pos, folder_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header label
        header = QLabel("  📁  Thư mục")
        style(header, 
            "background-color: @fill_hover; color: @text_secondary; "
            "padding: 8px 8px; font-size: 8.5pt; font-weight: 600; "
            "border-bottom: 1px solid @stroke_control;"
        )
        layout.addWidget(header)

        # File system model (directories only)
        self.model = QFileSystemModel()
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.model.setRootPath("")   # Show all drives

        # Tree view
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(""))
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.setSortingEnabled(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setWordWrap(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # Hide extra columns (size, type, date)
        for col in range(1, 4):
            self.tree.hideColumn(col)

        self.tree.clicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

    def _on_item_clicked(self, index: QModelIndex):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.folder_selected.emit(path)

    def _on_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if index.isValid():
            path = Path(self.model.filePath(index))
            if path.is_dir():
                global_pos = self.tree.viewport().mapToGlobal(pos)
                self.folder_context_menu_requested.emit(global_pos, path)

    def get_selected_path(self) -> Optional[Path]:
        index = self.tree.currentIndex()
        if index.isValid():
            p = Path(self.model.filePath(index))
            if p.is_dir():
                return p
        return None

    def expand_to(self, path: Path):
        """Expand tree to show and select `path`."""
        index = self.model.index(str(path))
        if index.isValid():
            self.tree.expand(index)
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

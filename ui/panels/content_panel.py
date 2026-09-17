"""
ui/panels/content_panel.py
Center panel: displays files in the current directory.
Supports modern Media Card grid view and Detail view.
Includes QuickLook (Spacebar) triggering, empty dropzone states, and drag-and-drop file import.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QDir, QSortFilterProxyModel, pyqtSignal,
    QModelIndex, QSize, QThread, QEvent, QTimer,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QFileSystemModel, QKeyEvent,
    QDragEnterEvent, QDragLeaveEvent, QDropEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QTableView,
    QLabel, QToolButton, QStackedWidget, QPushButton, QFrame,
    QAbstractItemView, QSizePolicy, QHeaderView, QApplication,
    QMessageBox,
)

from ui.widgets.svg_icons import get_svg_icon, get_svg_pixmap
from ui.panels.media_card_delegate import MediaCardDelegate


class EmptyDropzoneWidget(QWidget):
    """
    Interactive empty state view when a directory contains no items.
    Provides dashed border styling, quick action shortcuts, and drop target indicators.
    """
    create_folder_clicked = pyqtSignal()
    browse_clicked = pyqtSignal()
    go_up_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setContentsMargins(30, 30, 30, 30)

        # Dashed container box
        self.box = QFrame()
        self.box.setObjectName("dropzoneBox")
        self.box.setStyleSheet(
            "#dropzoneBox { "
            "   border: 2px dashed #334155; "
            "   border-radius: 12px; "
            "   background-color: rgba(17, 24, 39, 0.4); "
            "   padding: 40px; "
            "} "
            "#dropzoneBox[dragActive=\"true\"] { "
            "   border-color: #38bdf8; "
            "   background-color: rgba(56, 189, 248, 0.08); "
            "}"
        )
        self.box.setMinimumSize(420, 260)
        self.box.setMaximumSize(600, 340)

        box_lay = QVBoxLayout(self.box)
        box_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box_lay.setSpacing(12)

        # Large icon
        self.lbl_icon = QLabel()
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setPixmap(get_svg_pixmap("upload_cloud", "#38bdf8", 56))
        box_lay.addWidget(self.lbl_icon)

        # Title
        lbl_title = QLabel("Thư mục này đang trống")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("color: #f8fafc; font-size: 12pt; font-weight: 600;")
        box_lay.addWidget(lbl_title)

        # Subtitle
        lbl_sub = QLabel("Kéo thả tệp tin từ ngoài vào đây hoặc sử dụng các thao tác nhanh bên dưới")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        box_lay.addWidget(lbl_sub)

        box_lay.addSpacing(6)

        # Quick Actions Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        actions_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_new = QPushButton(" Tạo thư mục mới")
        btn_new.setIcon(get_svg_icon("folder_plus", "#38bdf8", 16))
        btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new.setStyleSheet(
            "QPushButton { background: #1e293b; color: #38bdf8; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: #334155; border-color: #38bdf8; }"
        )
        btn_new.clicked.connect(self.create_folder_clicked.emit)
        actions_row.addWidget(btn_new)

        btn_browse = QPushButton(" Mở thư mục khác")
        btn_browse.setIcon(get_svg_icon("folder_open", "#cbd5e1", 16))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.setStyleSheet(
            "QPushButton { background: #1e293b; color: #cbd5e1; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: #334155; }"
        )
        btn_browse.clicked.connect(self.browse_clicked.emit)
        actions_row.addWidget(btn_browse)

        btn_up = QPushButton(" Lên thư mục cha")
        btn_up.setIcon(get_svg_icon("arrow_up", "#cbd5e1", 16))
        btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_up.setStyleSheet(
            "QPushButton { background: #1e293b; color: #cbd5e1; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: #334155; }"
        )
        btn_up.clicked.connect(self.go_up_clicked.emit)
        actions_row.addWidget(btn_up)

        box_lay.addLayout(actions_row)
        lay.addWidget(self.box)

    def set_drag_active(self, active: bool):
        self.box.setProperty("dragActive", "true" if active else "false")
        self.box.style().unpolish(self.box)
        self.box.style().polish(self.box)


class ContentPanel(QWidget):
    """
    Displays files/folders in a directory.
    Supports grid (card view) and list (detail view).
    Integrates QuickLook modal on Spacebar, and Dropzone on empty folders.
    """
    file_selected          = pyqtSignal(Path)              # single file clicked
    folder_navigated       = pyqtSignal(Path)              # folder double-clicked/entered
    selection_changed      = pyqtSignal(list)              # list of selected paths
    context_menu_requested = pyqtSignal(object, list)       # (global_pos, selected_paths)
    quick_look_requested   = pyqtSignal(Path, list)        # (selected_path, all_files_in_dir)
    create_folder_requested= pyqtSignal(Path)              # Target parent dir
    browse_folder_requested= pyqtSignal()
    files_dropped          = pyqtSignal(list, Path)        # (src_paths, dest_dir)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir: Optional[Path] = None
        self._current_view_mode: str = "grid"
        self._is_empty: bool = False
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── View mode toolbar ──
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 5, 10, 5)

        self.lbl_count = QLabel("0 mục")
        self.lbl_count.setStyleSheet("color: #94a3b8; font-size: 8.5pt; font-weight: 500;")
        bar.addWidget(self.lbl_count)
        bar.addStretch()

        # Vector SVG toggle buttons
        btn_grid = QToolButton()
        btn_grid.setIcon(get_svg_icon("grid", "#94a3b8", 16, "#38bdf8"))
        btn_grid.setToolTip("Chế độ Lưới (Card View)")
        btn_grid.setCheckable(True)
        btn_grid.setChecked(True)
        btn_grid.setObjectName("viewToggle")
        btn_grid.clicked.connect(lambda: self._set_view("grid"))

        btn_list = QToolButton()
        btn_list.setIcon(get_svg_icon("list", "#94a3b8", 16, "#38bdf8"))
        btn_list.setToolTip("Chế độ Chi tiết (Detail View)")
        btn_list.setCheckable(True)
        btn_list.setObjectName("viewToggle")
        btn_list.clicked.connect(lambda: self._set_view("detail"))

        for btn in (btn_grid, btn_list):
            btn.setStyleSheet(
                "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 5px; "
                "padding: 4px 8px; } "
                "QToolButton:checked { background: #1e293b; border-color: #38bdf8; } "
                "QToolButton:hover { background: #1e293b; }"
            )
            bar.addWidget(btn)
        self._view_btns = (btn_grid, btn_list)

        bar_widget = QWidget()
        bar_widget.setLayout(bar)
        bar_widget.setStyleSheet("background: #0e1526; border-bottom: 1px solid #1e293b;")
        layout.addWidget(bar_widget)

        # ── Stacked views ──
        self.stack = QStackedWidget()

        # Model setup
        self.model = QFileSystemModel()
        self.model.setFilter(
            QDir.Filter.Files | QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot
        )

        # ── Page 0: Grid / Media Card View ──
        self.grid_view = QListView()
        self.grid_view.setModel(self.model)
        self.grid_view.setViewMode(QListView.ViewMode.IconMode)
        self.grid_view.setGridSize(QSize(120, 130))
        self.grid_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid_view.setSpacing(10)
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setMovement(QListView.Movement.Static)
        self.grid_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid_view.setDragEnabled(True)
        self.grid_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.grid_view.clicked.connect(self._on_item_clicked)
        self.grid_view.doubleClicked.connect(self._on_item_activated)
        self.grid_view.activated.connect(self._on_item_activated)
        self.grid_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_view.customContextMenuRequested.connect(self._on_context_menu)
        if self.grid_view.selectionModel():
            self.grid_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Custom Media Card Delegate
        self.media_card_delegate = MediaCardDelegate(self.model, self.grid_view)
        self.grid_view.setItemDelegate(self.media_card_delegate)

        # ── Page 1: Detail / Table View ──
        self.detail_view = QTableView()
        self.detail_view.setModel(self.model)
        self.detail_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.detail_view.setDragEnabled(True)
        self.detail_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.detail_view.verticalHeader().setVisible(False)
        self.detail_view.horizontalHeader().setStretchLastSection(True)
        self.detail_view.setShowGrid(False)
        self.detail_view.setAlternatingRowColors(False)
        self.detail_view.clicked.connect(self._on_item_clicked)
        self.detail_view.doubleClicked.connect(self._on_item_activated)
        self.detail_view.activated.connect(self._on_item_activated)
        self.detail_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.detail_view.customContextMenuRequested.connect(self._on_context_menu)
        if self.detail_view.selectionModel():
            self.detail_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # ── Page 2: Empty Dropzone State ──
        self.dropzone = EmptyDropzoneWidget(self)
        self.dropzone.create_folder_clicked.connect(
            lambda: self.create_folder_requested.emit(self.current_dir or Path.home())
        )
        self.dropzone.browse_clicked.connect(self.browse_folder_requested.emit)
        self.dropzone.go_up_clicked.connect(self._on_go_up_clicked)

        self.stack.addWidget(self.grid_view)   # index 0 = grid
        self.stack.addWidget(self.detail_view) # index 1 = detail
        self.stack.addWidget(self.dropzone)    # index 2 = empty state
        layout.addWidget(self.stack)

        # Install event filters for Spacebar QuickLook
        self.grid_view.installEventFilter(self)
        self.detail_view.installEventFilter(self)

        # Wire model signals for instantaneous and accurate directory state
        self.model.directoryLoaded.connect(self._on_directory_loaded)
        self.model.rowsInserted.connect(self._on_rows_changed)
        self.model.rowsRemoved.connect(self._on_rows_changed)

    # ─────────────────────────────────────────────
    # Navigation & Directory Loading
    # ─────────────────────────────────────────────

    def load_directory(self, path: Path):
        self.current_dir = path
        root_index = self.model.setRootPath(str(path))
        self.grid_view.setRootIndex(root_index)
        self.detail_view.setRootIndex(root_index)

        # Check if already populated in model cache
        n = self.model.rowCount(root_index)
        if n > 0:
            self.lbl_count.setText(f"{n} mục")
            self._is_empty = False
            self._apply_view_stack()
        else:
            self.lbl_count.setText("Đang duyệt thư mục...")

    def _on_directory_loaded(self, loaded_path: str):
        if self.current_dir and Path(loaded_path).resolve() == self.current_dir.resolve():
            root_index = self.model.index(loaded_path)
            n = self.model.rowCount(root_index)
            self.lbl_count.setText(f"{n} mục")
            self._is_empty = (n == 0)
            if self._is_empty:
                self.stack.setCurrentIndex(2)  # Show dropzone
            else:
                self._apply_view_stack()

    def _on_rows_changed(self):
        if self.current_dir:
            root_index = self.model.index(str(self.current_dir))
            n = self.model.rowCount(root_index)
            self.lbl_count.setText(f"{n} mục")
            if n > 0 and self._is_empty:
                self._is_empty = False
                self._apply_view_stack()

    def filter_by(self, query: str):
        """Filter visible files by name substring."""
        self.model.setNameFilters([f"*{query}*"] if query else [])
        self.model.setNameFilterDisables(False)

    def _set_view(self, mode: str):
        self._current_view_mode = mode
        self.view_btns_update(mode)
        if not self._is_empty:
            self._apply_view_stack()

    def _apply_view_stack(self):
        idx = 0 if self._current_view_mode == "grid" else 1
        self.stack.setCurrentIndex(idx)

    def view_btns_update(self, active: str):
        self._view_btns[0].setChecked(active == "grid")
        self._view_btns[1].setChecked(active == "detail")

    def _on_go_up_clicked(self):
        if self.current_dir:
            parent = self.current_dir.parent
            if parent != self.current_dir:
                self.folder_navigated.emit(parent)

    # ─────────────────────────────────────────────
    # Item Events
    # ─────────────────────────────────────────────

    def _on_item_clicked(self, index):
        path = Path(self.model.filePath(index))
        if path.is_file():
            self.file_selected.emit(path)

    def _on_item_activated(self, index):
        path = Path(self.model.filePath(index))
        if path.is_dir():
            self.folder_navigated.emit(path)
        elif path.is_file():
            self.file_selected.emit(path)

    def _on_selection_changed(self):
        active_view = self.grid_view if self.stack.currentIndex() == 0 else self.detail_view
        indexes = active_view.selectionModel().selectedIndexes()
        seen = set()
        paths = []
        for idx in indexes:
            p = Path(self.model.filePath(idx))
            if p not in seen:
                seen.add(p)
                paths.append(p)
        self.selection_changed.emit(paths)

    def get_selected_paths(self) -> list[Path]:
        active_view = self.grid_view if self.stack.currentIndex() == 0 else self.detail_view
        indexes = active_view.selectionModel().selectedIndexes()
        seen = set()
        paths = []
        for idx in indexes:
            p = Path(self.model.filePath(idx))
            if p not in seen:
                seen.add(p)
                paths.append(p)
        return paths

    def get_all_files_in_dir(self) -> list[Path]:
        """Return all files in current directory ordered as in the view."""
        root_index = self.grid_view.rootIndex()
        count = self.model.rowCount(root_index)
        files = []
        for row in range(count):
            idx = self.model.index(row, 0, root_index)
            p = Path(self.model.filePath(idx))
            if p.is_file():
                files.append(p)
        return files

    def _on_context_menu(self, pos):
        active_view = self.grid_view if self.stack.currentIndex() == 0 else self.detail_view
        global_pos = active_view.viewport().mapToGlobal(pos)
        selected = self.get_selected_paths()
        idx = active_view.indexAt(pos)
        if idx.isValid():
            clicked_path = Path(self.model.filePath(idx))
            if clicked_path not in selected:
                selected = [clicked_path]
        self.context_menu_requested.emit(global_pos, selected)

    # ─────────────────────────────────────────────
    # Event Filter (Spacebar QuickLook)
    # ─────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj in (self.grid_view, self.detail_view):
            if event.type() == QEvent.Type.KeyPress:
                key_event: QKeyEvent = event
                if key_event.key() == Qt.Key.Key_Space:
                    selected = self.get_selected_paths()
                    if selected and selected[0].is_file():
                        all_files = self.get_all_files_in_dir()
                        self.quick_look_requested.emit(selected[0], all_files)
                        return True
        return super().eventFilter(obj, event)

    # ─────────────────────────────────────────────
    # Drag and Drop File Import
    # ─────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.dropzone.set_drag_active(True)
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self.dropzone.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.dropzone.set_drag_active(False)
        urls = event.mimeData().urls()
        if urls and self.current_dir:
            dropped_paths = []
            for u in urls:
                local_p = Path(u.toLocalFile())
                if local_p.exists():
                    dropped_paths.append(local_p)
            if dropped_paths:
                event.acceptProposedAction()
                self.files_dropped.emit(dropped_paths, self.current_dir)
                return
        super().dropEvent(event)

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
    QModelIndex, QSize, QThread, QEvent, QTimer, QPoint, QRect,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QFileSystemModel, QKeyEvent, QCursor,
    QDragEnterEvent, QDragLeaveEvent, QDropEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QTableView,
    QLabel, QToolButton, QStackedWidget, QPushButton, QFrame,
    QAbstractItemView, QSizePolicy, QHeaderView, QApplication,
    QMessageBox,
)

from ui.widgets.svg_icons import get_svg_icon, get_svg_pixmap
from ui.explorer_model import COL_DATE, COL_NAME, COL_SIZE, COL_TYPE, ExplorerFileSystemModel
from ui.panels.explorer_delegate import VIEW_ORDER, VIEW_SPECS, ExplorerItemDelegate
from ui.thumbnails import ThumbnailCache
from ui.theme import style, tok

# Ctrl + mouse wheel steps through these, like Explorer
ZOOM_ORDER = ["detail", "list", "small", "medium", "large", "xl"]


def default_view_for(path: Path) -> str:
    """Explorer's folder templates: Pictures / Videos open in Large icons, the rest in Details."""
    from PyQt6.QtCore import QStandardPaths
    L = QStandardPaths.StandardLocation
    for loc in (L.PicturesLocation, L.MoviesLocation):
        base = QStandardPaths.writableLocation(loc)
        if base:
            try:
                Path(path).resolve().relative_to(Path(base).resolve())
                return "large"
            except ValueError:
                pass
    return "detail"


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
        style(self.box, 
            "#dropzoneBox { "
            "   border: 2px dashed @stroke_control; "
            "   border-radius: 12px; "
            "   background-color: rgba(17, 24, 39, 0.4); "
            "   padding: 40px; "
            "} "
            "#dropzoneBox[dragActive=\"true\"] { "
            "   border-color: @accent; "
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
        self.lbl_icon.setPixmap(get_svg_pixmap("upload_cloud", tok("accent"), 56))
        box_lay.addWidget(self.lbl_icon)

        # Title
        lbl_title = QLabel("Thư mục này đang trống")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style(lbl_title, "color: @text_primary; font-size: 12pt; font-weight: 600;")
        box_lay.addWidget(lbl_title)

        # Subtitle
        lbl_sub = QLabel("Kéo thả tệp tin từ ngoài vào đây hoặc sử dụng các thao tác nhanh bên dưới")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setWordWrap(True)
        style(lbl_sub, "color: @text_secondary; font-size: 9pt;")
        box_lay.addWidget(lbl_sub)

        box_lay.addSpacing(6)

        # Quick Actions Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        actions_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_new = QPushButton(" Tạo thư mục mới")
        btn_new.setIcon(get_svg_icon("folder_plus", tok("accent"), 16))
        btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        style(btn_new, 
            "QPushButton { background: @fill_hover; color: @accent; border: 1px solid @stroke_control; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: @fill_selected; border-color: @accent; }"
        )
        btn_new.clicked.connect(self.create_folder_clicked.emit)
        actions_row.addWidget(btn_new)

        btn_browse = QPushButton(" Mở thư mục khác")
        btn_browse.setIcon(get_svg_icon("folder_open", tok("text_secondary"), 16))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        style(btn_browse, 
            "QPushButton { background: @fill_hover; color: @text_secondary; border: 1px solid @stroke_control; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: @fill_selected; }"
        )
        btn_browse.clicked.connect(self.browse_clicked.emit)
        actions_row.addWidget(btn_browse)

        btn_up = QPushButton(" Lên thư mục cha")
        btn_up.setIcon(get_svg_icon("arrow_up", tok("text_secondary"), 16))
        btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        style(btn_up, 
            "QPushButton { background: @fill_hover; color: @text_secondary; border: 1px solid @stroke_control; "
            "border-radius: 6px; padding: 6px 14px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background: @fill_selected; }"
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
    view_mode_changed      = pyqtSignal(str)               # a VIEW_SPECS key ('detail', 'large', ...)
    file_activated         = pyqtSignal(Path)              # double-click / Enter on a file: open it
    item_count_changed     = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir: Optional[Path] = None
        self._current_view_mode: str = "detail"
        self._folder_views: dict[str, str] = {}       # per-folder view, remembered like Explorer
        self._is_empty: bool = False
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Stacked views ──
        self.stack = QStackedWidget()

        # Model setup
        self.model = ExplorerFileSystemModel()
        self.model.setFilter(
            QDir.Filter.Files | QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot
        )

        # ── Page 0: Grid / Media Card View ──
        self.grid_view = QListView()
        self.grid_view.setModel(self.model)
        self.grid_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setMovement(QListView.Movement.Static)
        self.grid_view.setMouseTracking(True)                      # hover highlight
        self.grid_view.setFrameShape(QFrame.Shape.NoFrame)
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

        # Explorer item painting (icons / list / tiles / content) with Shell thumbnails
        self.item_delegate = ExplorerItemDelegate(self.grid_view)
        self.grid_view.setItemDelegate(self.item_delegate)

        # ── Page 1: Detail / Table View ──
        self.detail_view = QTableView()
        self.detail_view.setModel(self.model)
        self.detail_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.detail_view.setDragEnabled(True)
        self.detail_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.detail_view.verticalHeader().setVisible(False)
        self.detail_view.verticalHeader().setDefaultSectionSize(24)  # Explorer row: 30 physical px at 125%
        self.detail_view.setShowGrid(False)
        self.detail_view.setAlternatingRowColors(False)
        self.detail_view.setWordWrap(False)
        self.detail_view.setIconSize(QSize(16, 16))
        self.detail_view.setMouseTracking(True)
        self.detail_view.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_view.setSortingEnabled(True)
        self.detail_view.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        header = self.detail_view.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        # Explorer column order: Name | Date modified | Type | Size
        header.moveSection(header.visualIndex(COL_DATE), 1)
        header.moveSection(header.visualIndex(COL_TYPE), 2)
        header.moveSection(header.visualIndex(COL_SIZE), 3)
        for col, width in ((COL_NAME, 320), (COL_DATE, 150), (COL_TYPE, 130), (COL_SIZE, 90)):
            header.resizeSection(col, width)
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
        self.grid_view.viewport().installEventFilter(self)       # Ctrl + wheel zoom
        self.detail_view.viewport().installEventFilter(self)
        self._configure_list_view(VIEW_SPECS["large"])

        # Wire model signals for instantaneous and accurate directory state
        self.model.directoryLoaded.connect(self._on_directory_loaded)
        self.model.rowsInserted.connect(self._on_rows_changed)
        self.model.rowsRemoved.connect(self._on_rows_changed)

    # ─────────────────────────────────────────────
    # Navigation & Directory Loading
    # ─────────────────────────────────────────────

    def load_directory(self, path: Path):
        ThumbnailCache.instance().cancel_pending()        # stop fetching thumbnails for the old folder
        self.current_dir = path
        root_index = self.model.setRootPath(str(path))
        self.grid_view.setRootIndex(root_index)
        self.detail_view.setRootIndex(root_index)
        self._set_view(self._folder_views.get(self._folder_key(path)) or default_view_for(path), remember=False)

        # Check if already populated in model cache
        n = self.model.rowCount(root_index)
        if n > 0:
            self.item_count_changed.emit(n)
            self._is_empty = False
            self._apply_view_stack()

    def _on_directory_loaded(self, loaded_path: str):
        if self.current_dir and Path(loaded_path).resolve() == self.current_dir.resolve():
            root_index = self.model.index(loaded_path)
            n = self.model.rowCount(root_index)
            self.item_count_changed.emit(n)
            self._is_empty = (n == 0)
            if self._is_empty:
                self.stack.setCurrentIndex(2)  # Show dropzone
            else:
                self._apply_view_stack()

    def _on_rows_changed(self):
        if self.current_dir:
            root_index = self.model.index(str(self.current_dir))
            n = self.model.rowCount(root_index)
            self.item_count_changed.emit(n)
            if n > 0 and self._is_empty:
                self._is_empty = False
                self._apply_view_stack()

    def filter_by(self, query: str):
        """Filter visible files by name substring."""
        self.model.setNameFilters([f"*{query}*"] if query else [])
        self.model.setNameFilterDisables(False)

    @staticmethod
    def _folder_key(path: Path) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    def _set_view(self, mode: str, remember: bool = True):
        mode = "large" if mode == "grid" else mode          # old name of the icon view
        if mode not in VIEW_SPECS:
            return
        changed = mode != self._current_view_mode
        self._current_view_mode = mode
        if remember and self.current_dir is not None:
            self._folder_views[self._folder_key(self.current_dir)] = mode
        if mode != "detail":
            self._configure_list_view(VIEW_SPECS[mode])
        if not self._is_empty:
            self._apply_view_stack()
        if changed:
            self.view_mode_changed.emit(mode)

    def set_view(self, mode: str):
        """Public view switch: any VIEW_SPECS key ('grid' is accepted for 'large')."""
        self._set_view(mode)

    def _configure_list_view(self, spec):
        gv = self.grid_view
        L = QListView
        if spec.kind in ("icon", "tile"):
            gv.setViewMode(L.ViewMode.IconMode)
            gv.setFlow(L.Flow.LeftToRight)
            gv.setWrapping(True)
        else:
            gv.setViewMode(L.ViewMode.ListMode)
            gv.setFlow(L.Flow.TopToBottom if (spec.flow_down or spec.kind == "content") else L.Flow.LeftToRight)
            gv.setWrapping(spec.kind == "row")
        gv.setGridSize(spec.cell if spec.cell is not None else QSize())
        gv.setSpacing(0)
        gv.setIconSize(QSize(spec.icon, spec.icon))
        gv.setMovement(L.Movement.Static)
        gv.setResizeMode(L.ResizeMode.Adjust)
        self.item_delegate.set_spec(spec)
        gv.doItemsLayout()
        gv.viewport().update()

    def zoom(self, steps: int):
        """Ctrl + wheel: step through Details, List, Small, Medium, Large, Extra large icons."""
        cur = self._current_view_mode if self._current_view_mode in ZOOM_ORDER else "large"
        i = max(0, min(len(ZOOM_ORDER) - 1, ZOOM_ORDER.index(cur) + steps))
        self.set_view(ZOOM_ORDER[i])

    @property
    def view_mode(self) -> str:
        return self._current_view_mode

    def sort_by(self, column: int, order: Qt.SortOrder):
        """Sort both views (they share the model) like Explorer's Sort menu."""
        self.detail_view.setSortingEnabled(True)
        self.detail_view.sortByColumn(column, order)

    def _apply_view_stack(self):
        self.stack.setCurrentIndex(1 if self._current_view_mode == "detail" else 0)

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
            self.file_activated.emit(path)

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

    def active_view(self):
        return self.grid_view if self.stack.currentIndex() == 0 else self.detail_view

    def selection_anchor(self) -> QPoint:
        """Global position for a keyboard-opened menu (Shift+F10): the current item, else the view."""
        view = self.active_view()
        idx = view.currentIndex()
        rect = view.visualRect(idx) if idx.isValid() else QRect()
        if rect.isValid() and view.viewport().rect().intersects(rect):
            return view.viewport().mapToGlobal(rect.center())
        return view.viewport().mapToGlobal(view.viewport().rect().center())

    def _on_context_menu(self, pos):
        active_view = self.active_view()
        global_pos = active_view.viewport().mapToGlobal(pos)
        selected = self.get_selected_paths()
        idx = active_view.indexAt(pos)
        if idx.isValid():
            clicked_path = Path(self.model.filePath(idx))
            if clicked_path not in selected:
                selected = [clicked_path]
        elif active_view.viewport().mapFromGlobal(QCursor.pos()) == pos:
            # Explorer: right-clicking empty space is about the folder, not the old selection
            # (the keyboard Menu key reports a position away from the cursor and keeps it)
            active_view.clearSelection()
            selected = []
        self.context_menu_requested.emit(global_pos, selected)

    # ─────────────────────────────────────────────
    # Event Filter (Spacebar QuickLook)
    # ─────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Wheel and obj in (self.grid_view.viewport(), self.detail_view.viewport())
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            delta = event.angleDelta().y()
            if delta:
                self.zoom(1 if delta > 0 else -1)
            return True
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

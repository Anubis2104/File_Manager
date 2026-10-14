"""
ui/main_window.py  (v2 — fully wired)
Main application window — Windows File Explorer style layout.
All panels, workers, and dialogs are connected here.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QThread, QObject, pyqtSignal, QTimer, QSize
from PyQt6.QtGui   import QIcon, QKeySequence, QAction, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QLineEdit, QFileDialog, QMessageBox,
    QSizePolicy, QFrame, QToolButton, QMenu, QToolBar,
    QInputDialog,
)

from ui.panels.tree_panel       import TreePanel
from ui.panels.content_panel    import ContentPanel
from ui.panels.preview_panel    import PreviewPanel
from ui.panels.right_dock_panel import RightDockPanel
from ui.panels.dup_preview_panel import DupPreviewPanel
from ui.panels.inspector_panel  import InspectorPanel
from ui.widgets.toolbar         import AppToolBar
from ui.widgets.statusbar       import AppStatusBar
from ui.widgets.workspace_tabs  import WorkspaceTabBar
from ui.widgets.background_layer import BackgroundLayer
from ui.widgets.progress_dialog import TaskProgressDialog
from ui.widgets.quick_look_dialog import QuickLookDialog
from ui.widgets.command_palette import CommandPaletteDialog, PaletteCommand
from ui.widgets.svg_icons       import get_svg_icon
from core.background_manager    import load_appearance_settings
from ui.widgets.title_bar       import TitleBar
from ui.win_chrome              import IS_WINDOWS, WindowChrome
from utils.cuda_helper          import get_cuda_info
from ui.theme import theme, tok


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileManagerPro")
        self.setMinimumSize(1100, 680)
        self.resize(1400, 860)

        self._current_scan_files = []    # FileInfo list from last scan
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._running_threads: set[QThread] = set()
        self._running_workers: set[QObject] = set()

        # Explorer-style chrome: tabs in the title bar over a Mica backdrop (Windows only;
        # offscreen/tests keep the native title bar)
        self._chrome: Optional[WindowChrome] = None
        self._native_chrome = IS_WINDOWS and QApplication.platformName() == "windows"
        if self._native_chrome:
            # Keep the native frame (a frameless translucent window would be WS_EX_LAYERED:
            # click-through transparent pixels, no Mica); WindowChrome removes the caption
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.bg_layer = BackgroundLayer(self)
        self._apply_stylesheet()
        self._build_toolbar()
        self._build_central_widget()
        self._build_title_bar()
        self._build_statusbar()
        self._build_menu_actions()
        self._init_quick_look_and_palette()
        self._connect_signals()
        self._setup_shortcuts()
        self._load_app_state()
        self._apply_appearance_settings()

        init_dir = self._resolve_initial_directory()
        self.workspace_tabs.add_tab(init_dir)
        self._navigate_to(init_dir)

    def _resolve_initial_directory(self) -> Path:
        """Resolve starting directory from config/settings.json or fallback to Path.home()."""
        try:
            from utils.file_utils import get_app_dir
            cfg_path = get_app_dir() / "config" / "settings.json"
        except Exception:
            cfg_path = Path(__file__).resolve().parent.parent / "config" / "settings.json"
        if cfg_path.exists():
            try:
                import json
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                custom_dir = data.get("general", {}).get("default_directory", "").strip()
                if custom_dir:
                    p = Path(custom_dir)
                    if p.is_dir():
                        return p
            except Exception:
                pass
        return Path.home()


    # ─────────────────────────────────────────────
    # Stylesheet
    # ─────────────────────────────────────────────

    def _apply_stylesheet(self):
        # The app-wide Explorer stylesheet is owned by ui.theme; install it when the
        # window is created without main.py (tests, embedding).
        from ui.theme import theme
        if theme()._app is None:
            theme().install(QApplication.instance())

    # ─────────────────────────────────────────────
    # Menu actions (wired to toolbar + context menu)
    # ─────────────────────────────────────────────

    def _build_menu_actions(self):
        tb = QToolBar("Thao tác", self)
        tb.setMovable(False)
        tb.setObjectName("actionsToolbar")
        tb.setIconSize(QSize(16, 16))

        # Rename action
        self.act_rename = tb.addAction(get_svg_icon("rename", tok("accent"), 16), "Đổi tên hàng loạt")
        self.act_rename.setToolTip("Đổi tên file theo cú pháp chuẩn (Ctrl+R)")
        self.act_rename.triggered.connect(self._open_rename_dialog)
        self.act_rename.setEnabled(True)

        # Queue Rename action (Drag-and-drop sequential)
        self.act_queue_rename = tb.addAction(get_svg_icon("queue", tok("accent"), 16), "Đổi tên Hàng đợi (Kéo thả)")
        self.act_queue_rename.setToolTip("Sắp xếp thứ tự kéo thả thủ công kèm đánh số thứ tự [STT]_[Tên cũ]")
        self.act_queue_rename.triggered.connect(lambda: self._open_queue_rename_dialog())
        self.act_queue_rename.setEnabled(True)

        tb.addSeparator()

        # Convert action
        self.act_convert = tb.addAction(get_svg_icon("convert", tok("accent"), 16), "Chuyển đổi định dạng")
        self.act_convert.setToolTip("Chuyển đổi ảnh/video sang định dạng khác")
        self.act_convert.triggered.connect(self._open_convert_dialog)

        tb.addSeparator()

        # Strip metadata
        self.act_strip_meta = tb.addAction(get_svg_icon("shield", tok("accent"), 16), "Xóa Metadata")
        self.act_strip_meta.setToolTip("Xóa metadata, bảo toàn ngày tháng tạo gốc")
        self.act_strip_meta.triggered.connect(self._strip_metadata)
        self.act_strip_meta.setEnabled(True)

        tb.addSeparator()

        # Clean empty folders
        self.act_clean = tb.addAction(get_svg_icon("trash", tok("accent"), 16), "Xóa thư mục rỗng")
        self.act_clean.setToolTip("Tìm và đưa thư mục rỗng vào thùng rác")
        self.act_clean.triggered.connect(self._clean_empty_folders)

        tb.addSeparator()

        # Inspector action
        self.act_inspector = tb.addAction(get_svg_icon("inspector", tok("accent"), 16), "Kiểm định Byte")
        self.act_inspector.setToolTip("Kiểm định cấu trúc, gọt overlay và quét mã độc")
        self.act_inspector.triggered.connect(lambda: self.tab_widget.setCurrentIndex(2))

        tb.addSeparator()

        # Restore from log
        self.act_restore = tb.addAction(get_svg_icon("refresh", tok("accent"), 16), "Khôi phục từ Log")
        self.act_restore.setToolTip("Khôi phục tên gốc từ file log")
        self.act_restore.triggered.connect(self._open_restore_dialog)

        tb.addSeparator()

        # Auto Organize action
        self.act_organize = tb.addAction(get_svg_icon("folder_plus", tok("accent"), 16), "Tự động sắp xếp")
        self.act_organize.setToolTip("Gom nhóm file vào thư mục con theo ngày hoặc loại")
        self.act_organize.triggered.connect(self._open_organize_dialog)

        tb.addSeparator()

        # Stats action
        self.act_stats = tb.addAction(get_svg_icon("stats", tok("accent"), 16), "Thống kê")
        self.act_stats.setToolTip("Phân tích dung lượng và phân bổ file")
        self.act_stats.triggered.connect(self._open_stats_dialog)

        tb.addSeparator()

        # Settings action
        self.act_settings = tb.addAction(get_svg_icon("settings", tok("accent"), 16), "Cài đặt")
        self.act_settings.setToolTip("Cấu hình hệ thống & AI")
        self.act_settings.triggered.connect(self._open_settings_dialog)

        tb.addSeparator()

        # Logcat action
        self.act_logcat = tb.addAction(get_svg_icon("logcat", tok("accent"), 16), "Logcat (F12)")
        self.act_logcat.setToolTip("Mở bảng điều khiển theo dõi Logcat trực tiếp (F12)")
        self.act_logcat.triggered.connect(self._open_logcat_dialog)

        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, tb)

    # ─────────────────────────────────────────────
    # Toolbar
    # ─────────────────────────────────────────────

    def _build_toolbar(self):
        self.toolbar = AppToolBar(self)
        self.toolbar.setObjectName("addressRow")
        self.addToolBar(self.toolbar)
        self.toolbar.navigate_requested.connect(self._navigate_to)
        self.toolbar.refresh_requested.connect(self._refresh)
        self.toolbar.search_requested.connect(self._on_search)

    # ─────────────────────────────────────────────
    # Central Widget
    # ─────────────────────────────────────────────

    def _build_central_widget(self):
        central = QWidget()
        central.setObjectName("mainCentralWidget")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        root_layout.addWidget(self.tab_widget)

        # ── Tab 1: File Explorer ──
        browse_tab = QWidget()
        browse_layout = QVBoxLayout(browse_tab)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(0)

        # Feature 5: Multi-tab workspace bar (browser-style tabs)
        # Tabs live in the title bar (see _build_title_bar), like Explorer
        self.workspace_tabs = WorkspaceTabBar(self)

        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.h_splitter.setChildrenCollapsible(False)

        self.tree_panel = TreePanel()
        self.tree_panel.setMinimumWidth(200)
        self.h_splitter.addWidget(self.tree_panel)

        right_splitter = QSplitter(Qt.Orientation.Horizontal)
        right_splitter.setChildrenCollapsible(False)

        self.content_panel = ContentPanel()
        right_splitter.addWidget(self.content_panel)

        # Feature 1: Dual-mode Right Dock (PreviewPanel <-> QueueDockWidget)
        self.right_dock = RightDockPanel(self)
        self.right_dock.setMinimumWidth(260)
        self.right_dock.setMaximumWidth(460)
        right_splitter.addWidget(self.right_dock)
        right_splitter.setSizes([850, 310])

        self.h_splitter.addWidget(right_splitter)
        self.h_splitter.setSizes([220, 1000])

        browse_layout.addWidget(self.h_splitter)
        self.tab_widget.addTab(browse_tab, "Trình duyệt tệp")

        # ── Tab 2: Duplicates ──
        self.dup_preview = DupPreviewPanel()
        self.tab_widget.addTab(self.dup_preview, "Quản lý trùng lặp")

        # ── Tab 3: Security & Inspector ──
        self.inspector_panel = InspectorPanel(self)
        self.tab_widget.addTab(self.inspector_panel, "Kiểm định & Bảo mật")

    # ─────────────────────────────────────────────
    # Status Bar
    # ─────────────────────────────────────────────

    def _build_statusbar(self):
        self.app_statusbar = AppStatusBar(self)
        self.setStatusBar(self.app_statusbar)
        cuda = get_cuda_info()
        self.app_statusbar.set_cuda_info(str(cuda))

    # ─────────────────────────────────────────────
    # Signals
    # ─────────────────────────────────────────────

    def _init_quick_look_and_palette(self):
        """Initialize and populate the Spotlight-style Command Palette and QuickLook modal."""
        self.quick_look_dialog = QuickLookDialog(self)
        self.command_palette = CommandPaletteDialog(self)

        cmds: list[PaletteCommand] = [
            PaletteCommand("Hành động", "Đổi tên hàng loạt tệp...", "rename", "Ctrl+R", self._open_rename_dialog),
            PaletteCommand("Hành động", "Đổi tên Hàng đợi (Kéo thả, kèm STT)...", "queue", "", self._open_queue_rename_dialog),
            PaletteCommand("Hành động", "Chuyển đổi định dạng ảnh/video...", "convert", "Ctrl+Shift+C", self._open_convert_dialog),
            PaletteCommand("Hành động", "Xóa Metadata tệp (Bảo toàn ngày gốc)", "shield", "", self._strip_metadata),
            PaletteCommand("Hành động", "Xóa thư mục rỗng vào thùng rác", "trash", "", self._clean_empty_folders),
            PaletteCommand("Hành động", "Quét tìm tệp trùng lặp (pHash / DINOv2)", "duplicate", "", lambda: (self.tab_widget.setCurrentIndex(1), self._start_dup_scan())),
            PaletteCommand("Hành động", "Kiểm định Byte, Gọt Overlay & Quét rủi ro", "inspector", "", lambda: self.tab_widget.setCurrentIndex(2)),
            PaletteCommand("Hành động", "Thống kê dung lượng & phân bổ tệp", "stats", "", self._open_stats_dialog),
            PaletteCommand("Hành động", "Khôi phục tên gốc từ Log...", "refresh", "", self._open_restore_dialog),
            PaletteCommand("Hành động", "Tự động sắp xếp tệp theo ngày/loại...", "folder_plus", "", self._open_organize_dialog),
            PaletteCommand("Xem trước", "Xem trước tệp tức thì (QuickLook)", "eye", "Space", self._trigger_quick_look_from_active_view),
            PaletteCommand("Tệp tin", "Tạo thư mục mới tại đây", "folder_plus", "", lambda: self._create_new_folder(self.content_panel.current_dir or Path.home())),
            PaletteCommand("Không gian", "Thêm Tab duyệt mới", "plus", "Ctrl+T", lambda: self.workspace_tabs.add_tab(self.content_panel.current_dir or Path.home())),
            PaletteCommand("Không gian", "Đóng Tab hiện tại", "close", "Ctrl+W", lambda: self.workspace_tabs.close_tab(self.workspace_tabs.active_index)),
            PaletteCommand("Giao diện", "Chế độ hiển thị: Lưới (Card View)", "grid", "", lambda: self.content_panel._set_view("grid")),
            PaletteCommand("Giao diện", "Chế độ hiển thị: Chi tiết (Detail View)", "list", "", lambda: self.content_panel._set_view("detail")),
            PaletteCommand("Hệ thống", "Cài đặt ứng dụng & Hình nền", "settings", "", self._open_settings_dialog),
            PaletteCommand("Hệ thống", "Mở bảng điều khiển Logcat", "logcat", "F12", self._open_logcat_dialog),
            PaletteCommand("Hệ thống", "Làm mới danh sách (F5)", "refresh", "F5", self._refresh),
            PaletteCommand("Điều hướng", "Nhảy tới: Thư mục cá nhân (Home)", "home", "", path_target=Path.home()),
        ]

        # Common user directories
        for name, icon in [("Desktop", "folder"), ("Downloads", "folder"), ("Documents", "folder"), ("Pictures", "image")]:
            p = Path.home() / name
            if p.exists():
                cmds.append(PaletteCommand("Điều hướng", f"Nhảy tới: {name}", icon, "", path_target=p))

        # Windows Drives
        import string
        for letter in string.ascii_uppercase:
            drive_p = Path(f"{letter}:\\")
            if drive_p.exists():
                cmds.append(PaletteCommand("Điều hướng", f"Ổ đĩa {letter}:", "drive", "", path_target=drive_p))

        self.command_palette.set_commands(cmds)

    # ─────────────────────────────────────────────
    # Signals
    # ─────────────────────────────────────────────

    def _connect_signals(self):
        self.tree_panel.folder_selected.connect(self._navigate_to)
        self.tree_panel.folder_context_menu_requested.connect(self._show_tree_context_menu)
        self.content_panel.folder_navigated.connect(self._navigate_to)
        self.content_panel.file_selected.connect(self.right_dock.show_file)
        self.content_panel.selection_changed.connect(self._on_content_selection)
        self.content_panel.context_menu_requested.connect(self._show_content_context_menu)
        self.right_dock.queue_completed.connect(self._refresh)
        # Browser-style tabs signals
        self.workspace_tabs.tab_switched.connect(self._on_workspace_tab_switched)
        self.workspace_tabs.new_tab_requested.connect(self._on_new_workspace_tab)
        # Wire dup scan button
        self.dup_preview.btn_scan.clicked.connect(self._start_dup_scan)

        # QuickLook & Command Palette
        self.toolbar.palette_requested.connect(self.command_palette.open_palette)
        self.command_palette.navigation_requested.connect(self._navigate_to)
        self.content_panel.quick_look_requested.connect(self._open_quick_look)
        self.quick_look_dialog.file_navigated.connect(lambda p: self.right_dock.show_file(p))

        # Empty Dropzone actions
        self.content_panel.create_folder_requested.connect(self._create_new_folder)
        self.content_panel.browse_folder_requested.connect(self._browse_folder_dialog)
        self.content_panel.files_dropped.connect(self._handle_files_dropped)

    def _open_quick_look(self, path: Path, file_list: Optional[list[Path]] = None):
        if path and path.is_file():
            files = file_list or self.content_panel.get_all_files_in_dir()
            self.quick_look_dialog.preview(path, files)

    def _trigger_quick_look_from_active_view(self):
        selected = self.content_panel.get_selected_paths()
        if selected and selected[0].is_file():
            self._open_quick_look(selected[0], self.content_panel.get_all_files_in_dir())

    def _create_new_folder(self, target_dir: Path):
        name, ok = QInputDialog.getText(self, "Tạo thư mục mới", "Tên thư mục mới:")
        if ok and name.strip():
            new_path = target_dir / name.strip()
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self._refresh()
                from core.app_logcat import logcat
                logcat.i("UI:Folder", f"Đã tạo thư mục mới: {new_path}")
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {e}")

    def _browse_folder_dialog(self):
        cur = self.content_panel.current_dir or Path.home()
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục", str(cur))
        if folder:
            self._navigate_to(Path(folder))

    def _handle_files_dropped(self, dropped_paths: list[Path], dest_dir: Path):
        import shutil
        from core.app_logcat import logcat
        logcat.i("UI:Dropzone", f"Nhận kéo thả {len(dropped_paths)} tệp vào {dest_dir}")
        count = 0
        for src in dropped_paths:
            try:
                dst = dest_dir / src.name
                if src.is_file():
                    shutil.copy2(src, dst)
                    count += 1
                elif src.is_dir() and src != dest_dir:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    count += 1
            except Exception as e:
                logcat.e("UI:Dropzone", f"Lỗi sao chép {src.name}: {e}")
        self._refresh()
        self.app_statusbar.lbl_path.setText(f"Đã sao chép {count} mục vào {dest_dir.name}")

    def _on_workspace_tab_switched(self, index: int, path: Path):
        self._navigate_to(path, from_tab_switch=True)

    def _on_new_workspace_tab(self, path: Path):
        self.workspace_tabs.add_tab(path)

    def _on_content_selection(self, selected: list):
        self.app_statusbar.update_selection(selected)
        self.act_rename.setEnabled(True)
        from core.app_logcat import logcat
        logcat.d("UI:Selection", f"Người dùng chọn {len(selected)} mục")

    def _show_tree_context_menu(self, global_pos, folder_path: Path):
        from core.app_logcat import logcat
        logcat.i("UI:TreeContextMenu", f"Menu chuột phải cây thư mục: {folder_path}")
        menu = QMenu(self)

        act_rename = menu.addAction(get_svg_icon("rename", tok("accent"), 16), "Đổi tên hàng loạt tệp trong thư mục này... (Ctrl+R)")
        act_rename.triggered.connect(lambda: self._open_rename_dialog(target_folders=[folder_path]))

        act_queue = menu.addAction(get_svg_icon("queue", tok("accent"), 16), "Đổi tên theo hàng đợi kéo thả (Kèm STT)...")
        act_queue.triggered.connect(lambda: self._open_queue_rename_dialog(target_folder=folder_path))

        act_open = menu.addAction(get_svg_icon("folder_open", tok("text_secondary"), 16), "Mở thư mục này")
        act_open.triggered.connect(lambda: self._navigate_to(folder_path))

        menu.addSeparator()

        act_dup = menu.addAction(get_svg_icon("duplicate", tok("accent"), 16), "Quét tìm trùng lặp cây thư mục này...")
        act_dup.triggered.connect(lambda: (self._navigate_to(folder_path), self.tab_widget.setCurrentIndex(1), self._start_dup_scan()))

        act_meta = menu.addAction(get_svg_icon("shield", tok("accent"), 16), "Xóa Metadata các tệp trong thư mục...")
        act_meta.triggered.connect(lambda: self._strip_metadata(target_folder=folder_path))

        act_convert = menu.addAction(get_svg_icon("convert", tok("accent"), 16), "Chuyển đổi định dạng ảnh/video...")
        act_convert.triggered.connect(lambda: self._open_convert_dialog(target_folder=folder_path))

        act_org = menu.addAction(get_svg_icon("folder_plus", tok("accent"), 16), "Tự động sắp xếp tệp trong thư mục...")
        act_org.triggered.connect(lambda: self._open_organize_dialog(target_folder=folder_path))

        act_stats = menu.addAction(get_svg_icon("stats", tok("accent"), 16), "Thống kê chi tiết thư mục này...")
        act_stats.triggered.connect(lambda: self._open_stats_dialog(target_folder=folder_path))

        menu.addSeparator()

        act_copy = menu.addAction(get_svg_icon("copy", tok("text_secondary"), 16), "Sao chép đường dẫn")
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(str(folder_path)))

        menu.exec(global_pos)

    def _show_content_context_menu(self, global_pos, selected_paths: list[Path]):
        from core.app_logcat import logcat
        logcat.i("UI:ContextMenu", f"Menu chuột phải mở cho {len(selected_paths)} mục tại toạ độ ({global_pos.x()}, {global_pos.y()})")
        menu = QMenu(self)

        selected_folders = [p for p in selected_paths if p.is_dir()]
        selected_files = [p for p in selected_paths if p.is_file()]

        if selected_files:
            act_peek = menu.addAction(get_svg_icon("eye", tok("accent"), 16), "Xem trước nhanh (Space)")
            act_peek.triggered.connect(lambda: self._open_quick_look(selected_files[0]))
            menu.addSeparator()

        if selected_folders:
            folder_text = selected_folders[0].name if len(selected_folders) == 1 else f"{len(selected_folders)} thư mục"
            act_rename = menu.addAction(get_svg_icon("rename", tok("accent"), 16), f"Đổi tên hàng loạt tệp trong {folder_text}... (Ctrl+R)")
            act_rename.triggered.connect(lambda: self._open_rename_dialog(target_folders=selected_folders))

            act_queue = menu.addAction(get_svg_icon("queue", tok("accent"), 16), f"Đổi tên hàng đợi kéo thả trong {folder_text}...")
            act_queue.triggered.connect(lambda: self._open_queue_rename_dialog(target_folder=selected_folders[0]))
        elif selected_files:
            act_rename = menu.addAction(get_svg_icon("rename", tok("accent"), 16), f"Đổi tên hàng loạt ({len(selected_files)} tệp đã chọn) (Ctrl+R)")
            act_rename.triggered.connect(lambda: self._open_rename_dialog(target_files=selected_files))
        else:
            act_rename = menu.addAction(get_svg_icon("rename", tok("accent"), 16), "Đổi tên toàn bộ tệp trong thư mục hiện tại (Ctrl+R)")
            act_rename.triggered.connect(self._open_rename_dialog)

            act_queue = menu.addAction(get_svg_icon("queue", tok("accent"), 16), "Đổi tên hàng đợi kéo thả thư mục hiện tại...")
            act_queue.triggered.connect(lambda: self._open_queue_rename_dialog())

        act_convert = menu.addAction(get_svg_icon("convert", tok("accent"), 16), "Chuyển đổi định dạng (Ctrl+Shift+C)")
        act_convert.triggered.connect(lambda: self._open_convert_dialog(target_folder=selected_folders[0] if selected_folders else None))

        menu.addSeparator()

        act_meta = menu.addAction(get_svg_icon("shield", tok("accent"), 16), "Xóa Metadata")
        act_meta.triggered.connect(lambda: self._strip_metadata(target_folder=selected_folders[0] if selected_folders else None))

        act_org = menu.addAction(get_svg_icon("folder_plus", tok("accent"), 16), "Tự động sắp xếp")
        act_org.triggered.connect(lambda: self._open_organize_dialog(target_folder=selected_folders[0] if selected_folders else None))

        menu.addSeparator()

        act_insp = menu.addAction(get_svg_icon("inspector", tok("accent"), 16), "Kiểm định tệp này")
        act_insp.triggered.connect(lambda: self.tab_widget.setCurrentIndex(2))

        menu.exec(global_pos)

    # ─────────────────────────────────────────────
    # Shortcuts
    # ─────────────────────────────────────────────

    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut
        QShortcut(QKeySequence("F5"),         self, activated=self._refresh)
        QShortcut(QKeySequence("Alt+Left"),   self, activated=self.toolbar.go_back)
        QShortcut(QKeySequence("Alt+Right"),  self, activated=self.toolbar.go_forward)
        QShortcut(QKeySequence("Alt+Up"),     self, activated=self.toolbar.go_up)
        QShortcut(QKeySequence("Ctrl+L"),     self, activated=self.toolbar.focus_address_bar)
        QShortcut(QKeySequence("Ctrl+F"),     self, activated=self.toolbar.focus_search)
        QShortcut(QKeySequence("Ctrl+R"),     self, activated=self._open_rename_dialog)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self._open_convert_dialog)
        QShortcut(QKeySequence("F12"),         self, activated=self._open_logcat_dialog)
        QShortcut(QKeySequence("Ctrl+K"),     self, activated=self.command_palette.open_palette)
        QShortcut(QKeySequence("Ctrl+P"),     self, activated=self.command_palette.open_palette)
        QShortcut(QKeySequence("Space"),      self, activated=self._trigger_quick_look_from_active_view)
        # Browser-style tab shortcuts
        QShortcut(QKeySequence("Ctrl+T"),     self, activated=lambda: self.workspace_tabs.add_tab(self.content_panel.current_dir or Path.home()))
        QShortcut(QKeySequence("Ctrl+W"),     self, activated=lambda: self.workspace_tabs.close_tab(self.workspace_tabs.active_index))
        QShortcut(QKeySequence("Ctrl+Tab"),   self, activated=lambda: self.workspace_tabs.cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self.workspace_tabs.cycle_tab(-1))


    # ─────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────

    def _navigate_to(self, path: Path, from_tab_switch: bool = False):
        if not path.is_dir():
            return
        from core.app_logcat import logcat
        logcat.i("UI:Navigation", f"Duyệt tới thư mục: {path}")
        if not from_tab_switch and hasattr(self, "workspace_tabs"):
            self.workspace_tabs.update_active_tab_path(path)
        self.content_panel.load_directory(path)
        self.tree_panel.expand_to(path)
        self.toolbar.push_path(path)
        self.app_statusbar.set_path(path)
        self.inspector_panel.set_directory(path)
        if hasattr(self, "right_dock"):
            self.right_dock.set_folder(path)
        self._current_scan_files = []


    def _refresh(self):
        current = self.content_panel.current_dir
        if current:
            self.content_panel.load_directory(current)

    def _on_search(self, query: str):
        self.content_panel.filter_by(query)

    # ─────────────────────────────────────────────
    # Directory Scanner
    # ─────────────────────────────────────────────

    def _start_scan(self):
        current = self.content_panel.current_dir
        if not current:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục.")
            return

        self._cancel_current_scan()

        from core.workers import ScanWorker, make_scan_thread
        self._scan_worker = ScanWorker(current, recursive=True, max_workers=8)
        self._scan_thread = make_scan_thread(self._scan_worker)
        self._running_threads.add(self._scan_thread)

        dlg = TaskProgressDialog("Đang duyệt cây thư mục...", parent=self)
        dlg.set_indeterminate(f"Đang duyệt cây thư mục: {current.name}")
        dlg.lbl_icon.setText("📁")
        dlg.attach_worker(self._scan_worker)
        dlg.cancelled.connect(self._scan_worker.cancel, Qt.ConnectionType.DirectConnection)

        self._scan_worker.file_found.connect(self._on_file_scanned)
        self._scan_worker.progress.connect(
            lambda cur, tot, name: (
                dlg.lbl_status.setText(f"Đã duyệt ({cur} file): {name}" if name else f"Đã duyệt: {cur} file")
            )
        )
        self._scan_worker.finished.connect(lambda files: (
            dlg.finish_task(f"Đã duyệt xong {len(files)} file"),
            self._on_scan_finished(files),
        ))
        self._scan_worker.cancelled.connect(
            lambda: (
                dlg.cancel_task("Đã dừng quét thư mục."),
                self.app_statusbar.lbl_path.setText("Đã dừng quét.")
            )
        )
        self._scan_worker.error.connect(
            lambda e: (
                dlg.reject(),
                self.app_statusbar.lbl_path.setText(f"Lỗi: {e}"),
                QMessageBox.critical(self, "Lỗi quét", e)
            )
        )

        self._current_scan_files = []
        self.app_statusbar.lbl_path.setText(f"Đang quét: {current} ...")
        dlg.show_centered()
        self._scan_thread.start()

    def _cancel_current_scan(self):
        if self._scan_worker:
            self._scan_worker.cancel()
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(300)
            if self._scan_thread in self._running_threads:
                self._running_threads.remove(self._scan_thread)
            self._scan_thread = None

    def _on_file_scanned(self, info):
        self._current_scan_files.append(info)
        n = len(self._current_scan_files)
        if n % 50 == 0:
            self.app_statusbar.lbl_path.setText(f"Đã quét: {n} file...")

    def _on_scan_finished(self, files: list):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(300)
            if self._scan_thread in self._running_threads:
                self._running_threads.remove(self._scan_thread)
            self._scan_thread = None

        self._current_scan_files = files
        n = len(files)
        self.app_statusbar.lbl_path.setText(f"Quét xong: {n} file")
        self.act_rename.setEnabled(n > 0)

    # ─────────────────────────────────────────────
    # Dialogs
    # ─────────────────────────────────────────────

    def _open_rename_dialog(
        self,
        target_folders: Optional[list[Path] | Path] = None,
        target_files: Optional[list[Path] | Path] = None,
    ):
        from ui.dialogs.rename_dialog import RenameDialog

        # Normalize target_folders if single Path
        if isinstance(target_folders, Path):
            target_folders = [target_folders]
        if isinstance(target_files, Path):
            target_files = [target_files]

        # Case 1: Specific target_folders explicitly passed (e.g. from context menu)
        if target_folders:
            folder = target_folders[0]
            # Check if we already have pre-scanned files covering this folder
            if self._current_scan_files and self.content_panel.current_dir:
                try:
                    matching = [
                        f for f in self._current_scan_files
                        if f.path == folder or folder in f.path.parents or f.path.is_relative_to(folder)
                    ]
                    if matching:
                        dlg = RenameDialog(files=matching, folder=folder, parent=self)
                        dlg.rename_completed.connect(lambda ops: self._refresh())
                        dlg.exec()
                        return
                except Exception:
                    pass
            # Otherwise open RenameDialog with folder target to scan recursively in background
            dlg = RenameDialog(folder=folder, parent=self)
            dlg.rename_completed.connect(lambda ops: self._refresh())
            dlg.exec()
            return

        # Case 2: Specific target_files explicitly passed
        if target_files:
            from core.scanner import DirectoryScanner
            scanner = DirectoryScanner(root=target_files[0].parent, recursive=False, max_workers=8)
            files = scanner.scan_paths(target_files)
            dlg = RenameDialog(files=files, parent=self)
            dlg.rename_completed.connect(lambda ops: self._refresh())
            dlg.exec()
            return

        # Case 3: Triggered via Toolbar button or Ctrl+R (no args passed)
        selected = self.content_panel.get_selected_paths()
        folders = [p for p in selected if p.is_dir()]
        files = [p for p in selected if p.is_file()]

        if folders:
            # User selected folder(s) in content panel
            self._open_rename_dialog(target_folders=folders)
            return

        if files:
            # User selected specific file(s) in content panel
            self._open_rename_dialog(target_files=files)
            return

        # Check if a folder is selected in tree panel
        tree_sel = self.tree_panel.get_selected_path()
        current = self.content_panel.current_dir or tree_sel

        if not current:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn một thư mục hoặc tệp để đổi tên.")
            return

        # Use current directory
        if self._current_scan_files and self.content_panel.current_dir == current:
            dlg = RenameDialog(files=self._current_scan_files, folder=current, parent=self)
        else:
            dlg = RenameDialog(folder=current, parent=self)

        dlg.rename_completed.connect(lambda ops: self._refresh())
        dlg.exec()

    def _open_convert_dialog(self, target_folder: Optional[Path] = None):
        from ui.dialogs.convert_dialog import ConvertDialog
        folder = target_folder or self.content_panel.current_dir
        dlg = ConvertDialog(folder=folder, parent=self)
        dlg.exec()

    def _open_queue_rename_dialog(self, target_folder: Optional[Path] = None):
        folder = target_folder or self.content_panel.current_dir or self.tree_panel.get_selected_path() or Path.home()
        self.tab_widget.setCurrentIndex(0)
        self.right_dock.open_queue_with_folder(folder)
        from core.app_logcat import logcat
        logcat.i("UI:QueueDock", f"Chuyển đổi thanh bên phải thành Hàng đợi Đổi tên: {folder}")

    def _open_restore_dialog(self):
        from ui.dialogs.log_restore_dialog import LogRestoreDialog
        dlg = LogRestoreDialog(parent=self)
        dlg.exec()

    def _open_organize_dialog(self, target_folder: Optional[Path] = None):
        current = target_folder or self.content_panel.current_dir
        if not current:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục.")
            return
        selected = self.content_panel.get_selected_paths() if not target_folder else []
        if not selected:
            # All files in current directory
            selected = [p for p in current.iterdir() if p.is_file()]
        if not selected:
            QMessageBox.information(self, "Thông báo", "Không tìm thấy file để sắp xếp.")
            return

        from ui.dialogs.organize_dialog import OrganizeDialog
        dlg = OrganizeDialog(files=selected, root_dir=current, parent=self)
        dlg.organize_completed.connect(lambda ops: self._refresh())
        dlg.exec()

    def _open_stats_dialog(self, target_folder: Optional[Path] = None):
        current = target_folder or self.content_panel.current_dir
        if not current:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục.")
            return
        from ui.dialogs.stats_dialog import StatsDialog
        dlg = StatsDialog(root=current, parent=self)
        dlg.exec()

    def _open_settings_dialog(self):
        from ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=self)
        if dlg.exec():
            self._apply_appearance_settings()

    def _strip_metadata(self, target_folder: Optional[Path] = None):
        from ui.dialogs.metadata_dialog import MetadataDialog
        current = target_folder or self.content_panel.current_dir
        selected = self.content_panel.get_selected_paths() if not target_folder else []
        dlg = MetadataDialog(current_dir=current, selected_files=selected, parent=self)
        dlg.metadata_stripped.connect(lambda res: self._refresh())
        dlg.exec()

    def _clean_empty_folders(self):
        current = self.content_panel.current_dir
        if not current:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục.")
            return

        from core.workers import CleanWorker
        # Dry-run first
        worker = CleanWorker(current, dry_run=True)
        thread = QThread(self)
        self._running_threads.add(thread)
        self._running_workers.add(worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        dlg = TaskProgressDialog("Đang quét thư mục rỗng...", parent=self)
        dlg.set_indeterminate("🔍 Đang quét và phân tích các thư mục rỗng...")
        dlg.lbl_icon.setText("🧹")
        dlg.attach_worker(worker)
        dlg.cancelled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)

        def _on_scan_prog(cur, tot, p):
            name = Path(p).name if p else ""
            if len(name) > 35:
                name = name[:32] + "..."
            dlg.lbl_status.setText(f"Đang quét ({cur} thư mục): {name}")

        worker.progress.connect(_on_scan_prog)

        def _on_dry_done(results):
            thread.quit()
            self._running_threads.discard(thread)
            self._running_workers.discard(worker)
            dlg.finish_task("Quét hoàn tất!")
            if not results:
                QMessageBox.information(self, "Thông báo", "Không tìm thấy thư mục rỗng.")
                return
            folders_str = "\n".join(str(r["path"]) for r in results[:10])
            if len(results) > 10:
                folders_str += f"\n... và {len(results)-10} thư mục nữa"
            reply = QMessageBox.question(
                self, f"Tìm thấy {len(results)} thư mục rỗng",
                f"Các thư mục sau sẽ được đưa vào Thùng rác:\n\n{folders_str}\n\nXác nhận?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._do_clean_folders([r["path"] for r in results])

        def _on_dry_cancelled():
            thread.quit()
            self._running_threads.discard(thread)
            self._running_workers.discard(worker)
            dlg.cancel_task("Đã dừng quét thư mục rỗng.")
            QMessageBox.information(self, "Đã hủy", "Đã dừng thao tác quét thư mục rỗng.")

        worker.finished.connect(_on_dry_done)
        worker.cancelled.connect(_on_dry_cancelled)
        worker.error.connect(lambda e: (
            thread.quit(),
            self._running_threads.discard(thread),
            self._running_workers.discard(worker),
            dlg.reject(),
            QMessageBox.critical(self, "Lỗi", e),
        ))
        dlg.show_centered()
        thread.start()

    def _do_clean_folders(self, folders: list[Path]):
        from core.workers import CleanWorker
        worker = CleanWorker(self.content_panel.current_dir, folders=folders, dry_run=False)
        thread = QThread(self)
        self._running_threads.add(thread)
        self._running_workers.add(worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        dlg = TaskProgressDialog("Đang xóa thư mục rỗng...", parent=self)
        dlg.set_task("Đang đưa thư mục rỗng vào Thùng rác...", total=len(folders), icon="🗑")
        dlg.attach_worker(worker)
        dlg.cancelled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)
        worker.progress.connect(dlg.update_progress)

        def _on_clean_done(results):
            thread.quit()
            self._running_threads.discard(thread)
            self._running_workers.discard(worker)
            dlg.finish_task("Đã dọn dẹp xong!")
            ok = sum(1 for r in results if r["success"])
            QMessageBox.information(
                self, "Hoàn thành",
                f"Đã đưa {ok}/{len(results)} thư mục rỗng vào Thùng rác."
            )
            self._refresh()

        def _on_clean_cancelled():
            thread.quit()
            self._running_threads.discard(thread)
            self._running_workers.discard(worker)
            dlg.cancel_task("Đã dừng xóa thư mục rỗng.")
            QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình xóa thư mục rỗng.")
            self._refresh()

        worker.finished.connect(_on_clean_done)
        worker.cancelled.connect(_on_clean_cancelled)
        worker.error.connect(lambda e: (
            thread.quit(),
            self._running_threads.discard(thread),
            self._running_workers.discard(worker),
            dlg.reject(),
            QMessageBox.critical(self, "Lỗi", e),
        ))
        dlg.show_centered()
        thread.start()

    # ─────────────────────────────────────────────
    # Duplicate Detection
    # ─────────────────────────────────────────────

    def _start_dup_scan(self):
        current = self.content_panel.current_dir
        if not current:
            QMessageBox.information(
                self, "Thông báo",
                "Vui lòng chọn thư mục trong tab 'File Explorer' trước."
            )
            return

        from duplicate.dup_manager import collect_image_paths
        from core.workers import DupScanWorker

        image_paths = collect_image_paths(current, recursive=True)
        if not image_paths:
            QMessageBox.information(
                self, "Thông báo",
                "Không tìm thấy ảnh trong thư mục này."
            )
            return

        # Map engine combo selection → mode
        mode_map = {0: "phash", 1: "dinov2", 2: "both"}
        mode = mode_map.get(self.dup_preview.engine_combo.currentIndex(), "both")

        self.dup_preview.btn_scan.setEnabled(False)
        self.dup_preview.lbl_summary.setText(
            f"Đang quét {len(image_paths)} ảnh với engine '{mode}'..."
        )

        worker = DupScanWorker(
            image_paths=image_paths,
            engine_mode=mode,
        )
        thread = QThread(self)
        self._running_threads.add(thread)
        self._running_workers.add(worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        dlg = TaskProgressDialog("Đang quét ảnh trùng lặp...", parent=self)
        dlg.set_task(f"🤖 Quét trùng lặp: {len(image_paths)} ảnh ({mode})", total=len(image_paths), icon="🤖")
        dlg.attach_worker(worker)
        dlg.cancelled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)

        worker.progress.connect(
            lambda d, t, msg: dlg.update_progress(d, t, msg)
        )
        worker.finished.connect(lambda groups: (
            dlg.finish_task(f"Tìm thấy {len(groups)} nhóm trùng lặp"),
            self._on_dup_finished(groups, thread, worker),
        ))
        worker.cancelled.connect(lambda: (
            thread.quit(),
            self._running_threads.discard(thread),
            self._running_workers.discard(worker),
            dlg.cancel_task("Đã dừng quét ảnh trùng lặp."),
            self.dup_preview.btn_scan.setEnabled(True),
            QMessageBox.information(self, "Đã hủy", "Đã dừng quét ảnh trùng lặp theo yêu cầu."),
        ))
        worker.error.connect(lambda e: (
            thread.quit(),
            self._running_threads.discard(thread),
            self._running_workers.discard(worker),
            dlg.reject(),
            QMessageBox.critical(self, "Lỗi quét", e),
            self.dup_preview.btn_scan.setEnabled(True),
        ))
        dlg.show_centered()
        thread.start()

    def _on_dup_finished(self, groups: list, thread: QThread, worker: Optional[object] = None):
        thread.quit()
        self._running_threads.discard(thread)
        if worker:
            self._running_workers.discard(worker)
        self.dup_preview.load_groups(groups)
        self.dup_preview.btn_scan.setEnabled(True)
        # Switch to Duplicates tab
        self.tab_widget.setCurrentIndex(1)

    def _open_logcat_dialog(self):
        from core.app_logcat import logcat
        logcat.i("UI:Dialog", "Mở bảng điều khiển Logcat trực tiếp (F12)")
        from ui.dialogs.logcat_dialog import LogcatDialog
        dlg = LogcatDialog(self)
        dlg.exec()

    # ─────────────────────────────────────────────
    # Window chrome (title bar, Mica, Snap Layouts)
    # ─────────────────────────────────────────────

    def _build_title_bar(self):
        from ui.widgets.workspace_tabs import WorkspaceTabButton
        self.title_bar = TitleBar(self, self.workspace_tabs)
        self.setMenuWidget(self.title_bar)
        # Tabs and their buttons keep their clicks; everything else in the bar drags the window
        self._is_title_interactive = lambda w: isinstance(w, (QToolButton, WorkspaceTabButton))
        # Bound method, not a lambda: PyQt drops the connection when this window is
        # destroyed, so a later theme switch never calls into a deleted window.
        theme().changed.connect(self._on_theme_changed)

    def showEvent(self, event):
        super().showEvent(event)
        if self._native_chrome and self._chrome is None:
            self._chrome = WindowChrome(self, self.title_bar, is_interactive=self._is_title_interactive)
            if not self._chrome.install(dark=theme().is_dark, backdrop=self._backdrop_kind):
                self._chrome = None   # native title bar stays; tabs sit in our bar below it
            self._apply_backdrop()
            self._sync_caption_space()
            QTimer.singleShot(250, self._sync_caption_space)

    def _sync_caption_space(self):
        if getattr(self, "_chrome", None) is not None:
            self.title_bar.set_caption_width(self._chrome.caption_buttons_width())

    def changeEvent(self, event):
        super().changeEvent(event)
        # Caption buttons change width between normal / maximized and across DPI changes
        if event.type() in (event.Type.WindowStateChange, event.Type.DevicePixelRatioChange):
            QTimer.singleShot(0, self._sync_caption_space)
            QTimer.singleShot(150, self._sync_caption_space)   # DWM may update bounds later

    def nativeEvent(self, event_type, message):
        if self._chrome is not None and event_type == b"windows_generic_MSG":
            handled, result = self._chrome.native_event(message)
            if handled:
                return True, result
        # Not super(): PyQt6 6.11 returns (False, None) from it and handing that back
        # to Qt crashes (access violation). QWidget::nativeEvent only returns false.
        return False, 0

    def _on_theme_changed(self, _tokens=None):
        self._apply_backdrop()

    def _apply_backdrop(self):
        kind = getattr(self, "_backdrop_kind", "tabbed")
        shows_backdrop = False
        if self._chrome is not None:
            shows_backdrop = self._chrome.set_backdrop(kind, theme().is_dark) and kind != "none"
        # Transparent window background only where the system draws a backdrop
        self.setProperty("backdrop", "system" if shows_backdrop else "solid")
        self.style().unpolish(self)
        self.style().polish(self)

    def closeEvent(self, event):
        """Safely terminate all background worker threads and persist UI state before closing."""
        from core.app_logcat import logcat
        logcat.i("SYS:Shutdown", "Đang dừng tất cả background workers...")

        # Signal tất cả workers dừng lại trước khi quit thread
        for worker in list(self._running_workers):
            try:
                if hasattr(worker, "cancel"):
                    worker.cancel()
            except Exception:
                pass

        self._cancel_current_scan()

        # Wait lâu hơn để workers nặng (DINOv2 inference, metadata rewrite) có thể thoát
        for t in list(self._running_threads):
            if t.isRunning():
                t.quit()
                t.wait(2000)   # 2s thay vì 300ms

        self._save_app_state()
        logcat.i("SYS:Exit", "Ứng dụng đóng lại. Kết thúc phiên làm việc.")
        event.accept()

    def _save_app_state(self):
        try:
            from PyQt6.QtCore import QSettings
            settings = QSettings("FileManagerPro", "MainWindow")
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("h_splitter", self.h_splitter.saveState())
        except Exception:
            pass

    def _load_app_state(self):
        try:
            from PyQt6.QtCore import QSettings
            settings = QSettings("FileManagerPro", "MainWindow")
            geom = settings.value("geometry")
            if geom:
                self.restoreGeometry(geom)
            split = settings.value("h_splitter")
            if split:
                self.h_splitter.restoreState(split)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "bg_layer"):
            self.bg_layer.setGeometry(self.rect())
            self.bg_layer.lower()
        # DWM settles the caption-button size only after the first layout / DPI pass
        self._sync_caption_space()

    def _apply_appearance_settings(self):
        cfg = load_appearance_settings()
        mode = cfg.get("background_mode", "default")
        blur_opacity = cfg.get("blur_opacity", 50)
        bg_type = cfg.get("background_type", "none")
        bg_file = cfg.get("background_file", "")
        opacity = cfg.get("overlay_opacity", 0.82)

        # 1. Update background wallpaper layer
        if hasattr(self, "bg_layer"):
            effective_bg = bg_type if mode == "custom" else "none"
            self.bg_layer.set_background(effective_bg, bg_file, opacity)
            self.bg_layer.setGeometry(self.rect())
            self.bg_layer.lower()

        # 2. System backdrop: Mica Alt (default) / Acrylic (blur) / none (custom wallpaper)
        self._backdrop_kind = {"blur": "acrylic", "custom": "none"}.get(mode, "tabbed")
        self._apply_backdrop()

        # 3. Dynamic styling for glassmorphism / wallpaper mode
        # Base Explorer stylesheet lives at app level (ui.theme); only overlays go here
        base_qss = ""

        if mode == "blur":
            # blur_opacity: 0 = fully transparent, 100 = dark frosted
            panel_alpha = 0.02 + (blur_opacity / 100.0) * 0.86
            toolbar_alpha = 0.10 + (blur_opacity / 100.0) * 0.78
            statusbar_alpha = 0.10 + (blur_opacity / 100.0) * 0.78
            border_alpha = max(0.04, min(0.28, 0.04 + (blur_opacity / 100.0) * 0.14))

            glass_extra = (
                "\n/* Glassmorphic Blur & Full Translucency */\n"
                "#mainCentralWidget { background: transparent; }\n"
                "QMainWindow { background: transparent; }\n"
                "QSplitter { background: transparent; }\n"
                "QTabWidget::pane { background: transparent; border: none; }\n"
                "TreePanel, ContentPanel, RightDockPanel, DupPreviewPanel, InspectorPanel {\n"
                f"    background-color: rgba(15, 23, 42, {panel_alpha:.2f});\n"
                f"    border: 1px solid rgba(255, 255, 255, {border_alpha:.2f});\n"
                "    border-radius: 8px;\n"
                "}\n"
                f"QToolBar {{ background-color: rgba(17, 24, 39, {toolbar_alpha:.2f}); }}\n"
                f"QStatusBar {{ background-color: rgba(15, 23, 42, {statusbar_alpha:.2f}); }}\n"
            )
            self.setStyleSheet(base_qss + glass_extra)
        elif mode == "custom":
            glass_extra = (
                "\n/* Wallpaper Translucency */\n"
                "#mainCentralWidget { background: transparent; }\n"
                "QMainWindow { background: transparent; }\n"
                "QSplitter { background: transparent; }\n"
                "QTabWidget::pane { background: transparent; border: none; }\n"
                "TreePanel, ContentPanel, RightDockPanel, DupPreviewPanel, InspectorPanel {\n"
                "    background-color: rgba(18, 24, 38, 0.80);\n"
                "    border: 1px solid rgba(255, 255, 255, 0.08);\n"
                "    border-radius: 8px;\n"
                "}\n"
                "QToolBar { background-color: rgba(17, 24, 39, 0.85); }\n"
                "QStatusBar { background-color: rgba(15, 23, 42, 0.85); }\n"
            )
            self.setStyleSheet(base_qss + glass_extra)
        else:
            # Default solid dark mode
            self.setStyleSheet(base_qss)

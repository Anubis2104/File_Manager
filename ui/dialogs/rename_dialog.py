"""
ui/dialogs/rename_dialog.py
Dialog for configuring and executing batch rename with recursive directory tree scanning,
live parameter display (EXIF date, resolution, size, orientation, status),
Token Chip Builder, hover thumbnail preview, and WAL log recording.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional, Union

from PyQt6.QtCore  import Qt, QThread, pyqtSignal, QEvent, QSettings
from PyQt6.QtGui   import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QTableWidget, QTableWidgetItem,
    QGroupBox, QFileDialog, QMessageBox,
    QHeaderView, QAbstractItemView, QWidget, QFrame, QApplication,
)

from core.scanner  import FileInfo, DirectoryScanner
from core.renamer  import RenameEngine
from core.logger   import RenameLogger
from core.workers  import RenameWorker, ScanWorker, make_scan_thread
from utils.file_utils import RenameOperation
from ui.widgets.hover_preview import HoverThumbnailPopup
from ui.widgets.progress_dialog import TaskProgressDialog
from ui.theme import qcolor, style


def _format_size(size_bytes: int) -> str:
    """Format bytes into a readable string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1048576:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1073741824:
        return f"{size_bytes / 1048576:.2f} MB"
    else:
        return f"{size_bytes / 1073741824:.2f} GB"


class RenameDialog(QDialog):
    """
    Comprehensive batch rename dialog:
    - Supports pre-scanned files OR recursive directory tree scanning.
    - 8-column parameter table (Subfolder, Old name, New name, Date/EXIF, Resolution/Orientation, Size, Type, Status).
    - Token Chip Builder: clickable chips to craft custom naming rules.
    - Hover Thumbnail Preview: floating preview tooltip with image thumbnail.
    - Real-time search/filter input.
    - State Persistence: remembers column widths, date format, and patterns.
    - Summary badges (folders, files, renaming count, collisions).
    - Clipboard/CSV export.
    - Asynchronous rename execution with progress and WAL logging.
    """
    rename_completed = pyqtSignal(list)    # list[RenameOperation]

    def __init__(
        self,
        files: Optional[list[FileInfo]] = None,
        folder: Optional[Union[Path, list[Path]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.files: list[FileInfo] = list(files) if files else []
        self.target_folder: Optional[Union[Path, list[Path]]] = folder
        self.root_dir: Optional[Path] = (
            folder if isinstance(folder, Path)
            else (folder[0] if isinstance(folder, list) and folder else None)
        )
        self.ops: list[RenameOperation] = []
        self._last_info_by_path: dict[Path, FileInfo] = {}

        # Threading for rename
        self._rename_thread: Optional[QThread] = None
        self._rename_worker: Optional[RenameWorker] = None

        # Threading for tree scan (if folder passed)
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[ScanWorker] = None

        # Window settings
        title_target = ""
        if isinstance(folder, Path):
            title_target = f" — Thư mục: {folder.name}"
        elif isinstance(folder, list) and folder:
            title_target = f" — {len(folder)} thư mục"
        elif self.files:
            title_target = f" — {len(self.files)} tệp"

        self.setWindowTitle(f"Đổi tên hàng loạt{title_target}")
        self.resize(1140, 680)
        self.setMinimumSize(940, 580)

        self._build_ui()
        self._load_settings()

        # If files were passed, refresh immediately; if folder passed, start recursive scan
        if self.files:
            self._refresh_preview()
        elif self.target_folder:
            self._start_folder_scan()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)



        # ── Settings group ──
        settings_group = QGroupBox("Cấu hình quy tắc đổi tên & Mẫu ghép Tokens")
        style(settings_group, 
            "QGroupBox { font-weight: 600; font-size: 9pt; border: 1px solid @stroke_control; "
            "border-radius: 6px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        sg_vlayout = QVBoxLayout(settings_group)
        sg_vlayout.setContentsMargins(10, 8, 10, 8)
        sg_vlayout.setSpacing(8)

        # Row 1: Date format, log file, checksum, copy button
        sg_row1 = QHBoxLayout()
        sg_row1.setSpacing(10)

        sg_row1.addWidget(QLabel("Định dạng ngày:"))
        self.date_fmt_combo = QComboBox()
        self.date_fmt_combo.addItems(["DDMMYY", "DDMMYYYY", "YYYYMMDD", "MMDDYY"])
        self.date_fmt_combo.setToolTip("Quy tắc hiển thị ngày tháng lấy từ EXIF hoặc ngày tạo tệp")
        self.date_fmt_combo.currentTextChanged.connect(self._refresh_preview)
        sg_row1.addWidget(self.date_fmt_combo)

        sg_row1.addWidget(QLabel("  Nhật ký (Log):"))
        self.log_path_edit = QLineEdit()
        self.log_path_edit.setPlaceholderText("rename_log.jsonl")
        self.log_path_edit.setText("rename_log.jsonl")
        self.log_path_edit.setFixedWidth(160)
        sg_row1.addWidget(self.log_path_edit)

        btn_browse_log = QPushButton("📁")
        btn_browse_log.setFixedWidth(30)
        btn_browse_log.setToolTip("Chọn vị trí lưu file nhật ký đổi tên")
        btn_browse_log.clicked.connect(self._browse_log)
        sg_row1.addWidget(btn_browse_log)

        self.chk_checksum = QCheckBox("Ghi Checksum MD5 (hỗ trợ khôi phục)")
        self.chk_checksum.setChecked(True)
        sg_row1.addWidget(self.chk_checksum)

        sg_row1.addStretch()

        self.btn_export = QPushButton("📋 Sao chép bảng")
        self.btn_export.setToolTip("Sao chép danh sách tệp & thông số xem trước vào Clipboard (dạng bảng)")
        self.btn_export.clicked.connect(self._copy_table_to_clipboard)
        sg_row1.addWidget(self.btn_export)

        sg_vlayout.addLayout(sg_row1)

        # Row 2: Token Chip Builder
        sg_row2 = QHBoxLayout()
        sg_row2.setSpacing(6)
        sg_row2.addWidget(QLabel("Mẫu tên tệp (Tokens):"))

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setText("{folder}_{date}_{orientation}_{resolution}")
        self.pattern_edit.setPlaceholderText("{folder}_{date}_{orientation}_{resolution}")
        self.pattern_edit.setFixedWidth(240)
        self.pattern_edit.textChanged.connect(self._refresh_preview)
        sg_row2.addWidget(self.pattern_edit)

        token_chips = [
            ("📁 {folder}", "{folder}"),
            ("📅 {date}", "{date}"),
            ("📐 {resolution}", "{resolution}"),
            ("🔤 {orientation}", "{orientation}"),
            ("🔢 {seq}", "{seq}"),
            ("🏷️ {original}", "{original}"),
        ]
        for label, token in token_chips:
            btn_chip = QPushButton(label)
            btn_chip.setCursor(Qt.CursorShape.PointingHandCursor)
            style(btn_chip, 
                "QPushButton { background-color: @fill_hover; color: @accent; border: 1px solid @stroke_control; "
                "border-radius: 4px; padding: 2px 6px; font-size: 8pt; font-weight: 500; }"
                "QPushButton:hover { background-color: @fill_selected; color: @text_primary; border-color: @accent; }"
            )
            btn_chip.clicked.connect(lambda checked, t=token: self._insert_token(t))
            sg_row2.addWidget(btn_chip)

        btn_reset_pattern = QPushButton("↺ Mặc định")
        style(btn_reset_pattern, 
            "QPushButton { background: transparent; color: @text_secondary; border: 1px dashed @stroke_control; "
            "border-radius: 4px; padding: 2px 6px; font-size: 8pt; }"
            "QPushButton:hover { color: @text_primary; border-color: @stroke_control; }"
        )
        btn_reset_pattern.clicked.connect(
            lambda: self.pattern_edit.setText("{folder}_{date}_{orientation}_{resolution}")
        )
        sg_row2.addWidget(btn_reset_pattern)

        sg_row2.addStretch()
        sg_vlayout.addLayout(sg_row2)

        layout.addWidget(settings_group)

        # ── Toolbar: Filter bar & Summary Cards ──
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Lọc nhanh theo tên tệp, thư mục con, định dạng, ngày... (Rà chuột vào hàng để xem ảnh thu nhỏ)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_table)
        filter_row.addWidget(self.search_edit, stretch=2)

        # Summary badges
        self.lbl_summary_files = QLabel("📁 0 thư mục | 📄 0 tệp")
        style(self.lbl_summary_files, 
            "background-color: @fill_hover; color: @text_secondary; border-radius: 4px; "
            "padding: 4px 8px; font-weight: 600; font-size: 8.5pt;"
        )
        filter_row.addWidget(self.lbl_summary_files)

        self.lbl_summary_rename = QLabel("✏️ 0 đổi tên")
        style(self.lbl_summary_rename, 
            "background-color: @success_bg; color: @success; border-radius: 4px; "
            "padding: 4px 8px; font-weight: 600; font-size: 8.5pt;"
        )
        filter_row.addWidget(self.lbl_summary_rename)

        self.lbl_summary_collision = QLabel("⚠️ 0 trùng lặp")
        style(self.lbl_summary_collision, 
            "background-color: @warning_bg; color: @warning; border-radius: 4px; "
            "padding: 4px 8px; font-weight: 600; font-size: 8.5pt;"
        )
        filter_row.addWidget(self.lbl_summary_collision)

        layout.addLayout(filter_row)

        # ── 8-Column Parameter Table with Hover Preview ──
        self.table = QTableWidget()
        headers = [
            "Thư mục con",
            "Tên gốc",
            "Tên mới dự kiến",
            "Ngày (EXIF / Tạo)",
            "Độ phân giải & Chiều",
            "Dung lượng",
            "Định dạng",
            "Trạng thái",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 210)
        self.table.setColumnWidth(2, 260)

        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        style(self.table, 
            "QTableWidget { gridline-color: @stroke_divider; selection-background-color: @accent; }"
            "QTableWidget::item { padding: 3px 6px; }"
        )

        # Enable hover thumbnail tracking
        self.table.setMouseTracking(True)
        self.table.viewport().installEventFilter(self)

        layout.addWidget(self.table)



        # ── Bottom row: Status & Actions ──
        bottom_row = QHBoxLayout()

        self.lbl_status = QLabel("")
        style(self.lbl_status, "color: @text_secondary; font-size: 8.5pt;")
        bottom_row.addWidget(self.lbl_status)

        bottom_row.addStretch()

        self.btn_preview = QPushButton("🔄  Làm mới preview")
        self.btn_preview.clicked.connect(self._refresh_preview)
        bottom_row.addWidget(self.btn_preview)

        self.btn_cancel = QPushButton("Hủy bỏ")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(self.btn_cancel)

        self.btn_execute = QPushButton("✔  Thực hiện đổi tên")
        self.btn_execute.setObjectName("btnPrimary")
        style(self.btn_execute, 
            "QPushButton#btnPrimary { background-color: @accent; color: @text_on_accent; "
            "font-weight: 600; padding: 6px 18px; border-radius: 5px; }"
            "QPushButton#btnPrimary:hover { background-color: @accent; }"
            "QPushButton#btnPrimary:disabled { background-color: @fill_selected; color: @text_tertiary; }"
        )
        self.btn_execute.clicked.connect(self._execute)
        bottom_row.addWidget(self.btn_execute)

        layout.addLayout(bottom_row)

    def _insert_token(self, token: str):
        """Insert a token chip into the pattern edit at the cursor position."""
        pos = self.pattern_edit.cursorPosition()
        cur = self.pattern_edit.text()
        sep = "_" if pos > 0 and cur[pos - 1] not in ("_", "{") else ""
        new_text = cur[:pos] + sep + token + cur[pos:]
        self.pattern_edit.setText(new_text)
        self.pattern_edit.setCursorPosition(pos + len(sep) + len(token))
        self.pattern_edit.setFocus()

    # ─────────────────────────────────────────────
    # Folder Scanning (Recursive Tree Traversal)
    # ─────────────────────────────────────────────

    def _start_folder_scan(self):
        """Start background recursive scanning for target folder(s)."""
        if not self.target_folder:
            return

        folders: list[Path] = (
            [self.target_folder] if isinstance(self.target_folder, Path)
            else self.target_folder
        )
        if not folders:
            return

        self.btn_execute.setEnabled(False)
        self.btn_preview.setEnabled(False)

        from core.workers import ScanWorker, make_scan_thread
        self.files.clear()

        target_name = folders[0].name if len(folders) == 1 else f"{len(folders)} thư mục"
        # Modal Progress Dialog for folder tree scan
        self._scan_progress_dlg = TaskProgressDialog("Đang duyệt cây thư mục...", parent=self)
        self._scan_progress_dlg.set_indeterminate(f"Đang duyệt đệ quy cây thư mục: {target_name} ...")
        self._scan_progress_dlg.lbl_icon.setText("🔍")

        # We scan all target folders
        self._scan_worker = ScanWorker(folders, recursive=True, max_workers=8)
        self._scan_thread = make_scan_thread(self._scan_worker)

        self._scan_progress_dlg.attach_worker(self._scan_worker)
        self._scan_progress_dlg.cancelled.connect(self._scan_worker.cancel, Qt.ConnectionType.DirectConnection)
        self._scan_progress_dlg.cancelled.connect(self._cancel_scan, Qt.ConnectionType.DirectConnection)
        self._scan_worker.file_found.connect(self._on_scan_file_found)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.cancelled.connect(self._on_scan_cancelled)
        self._scan_worker.error.connect(self._on_scan_error)

        self._scan_progress_dlg.show_centered()
        self._scan_thread.start()

    def _on_scan_file_found(self, info: FileInfo):
        self.files.append(info)
        n = len(self.files)
        if hasattr(self, "_scan_progress_dlg") and self._scan_progress_dlg:
            self._scan_progress_dlg.lbl_status.setText(f"Đang duyệt: {info.name} (Đã tìm thấy {n} tệp)")

    def _on_scan_progress(self, done: int, total: int, filename: str):
        if hasattr(self, "_scan_progress_dlg") and self._scan_progress_dlg:
            self._scan_progress_dlg.update_progress(done, total, filename)

    def _on_scan_finished(self, files: list):
        self._cleanup_scan_thread()
        if hasattr(self, "_scan_progress_dlg") and self._scan_progress_dlg:
            self._scan_progress_dlg.finish_task(f"Đã duyệt xong! Tìm thấy {len(files)} tệp.")
        self.files = files
        self.btn_preview.setEnabled(True)
        self.btn_execute.setEnabled(True)
        self._refresh_preview()

    def _on_scan_cancelled(self):
        self._cleanup_scan_thread()
        if hasattr(self, "_scan_progress_dlg") and self._scan_progress_dlg:
            self._scan_progress_dlg.cancel_task("Đã dừng quét cây thư mục.")
        self.btn_preview.setEnabled(True)
        self.btn_execute.setEnabled(len(self.files) > 0)
        self._refresh_preview()

    def _on_scan_error(self, err_msg: str):
        self._cleanup_scan_thread()
        if hasattr(self, "_scan_progress_dlg") and self._scan_progress_dlg:
            self._scan_progress_dlg.reject()
        self.btn_preview.setEnabled(True)
        self.btn_execute.setEnabled(len(self.files) > 0)
        QMessageBox.warning(self, "Cảnh báo khi quét", f"Lỗi trong quá trình quét: {err_msg}")
        self._refresh_preview()

    def _cancel_scan(self):
        if self._scan_worker:
            self._scan_worker.cancel()

    def _cleanup_scan_thread(self):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(400)
        self._scan_thread = None
        self._scan_worker = None

    # ─────────────────────────────────────────────
    # Preview Calculation & Table Population
    # ─────────────────────────────────────────────

    def _refresh_preview(self):
        date_fmt = self.date_fmt_combo.currentText()
        pattern = self.pattern_edit.text().strip() or None
        engine = RenameEngine(date_fmt=date_fmt, pattern=pattern, dry_run=True)
        self.ops = engine.plan(self.files)

        # Map FileInfo by path for quick lookup of parameters
        self._last_info_by_path = {f.path: f for f in self.files}

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.ops))

        num_changing = 0
        num_collisions = 0
        folders_seen = set()

        for row, op in enumerate(self.ops):
            info = self._last_info_by_path.get(op.src)
            folders_seen.add(op.src.parent)

            # 1. Subfolder path (relative to root if possible)
            subfolder_text = op.src.parent.name
            if self.root_dir:
                try:
                    rel = op.src.parent.relative_to(self.root_dir)
                    subfolder_text = str(rel) if str(rel) != "." else f"[Gốc] {self.root_dir.name}"
                except Exception:
                    subfolder_text = op.src.parent.name

            folder_item = QTableWidgetItem(f"📁 {subfolder_text}")
            folder_item.setToolTip(str(op.src.parent))

            # 2. Old name
            old_item = QTableWidgetItem(op.src.name)
            old_item.setToolTip(str(op.src))

            # 3. New name
            new_item = QTableWidgetItem(op.dst.name)
            is_changed = op.src.name != op.dst.name
            is_collision = False

            # Check if auto-collision suffix _001 was attached
            base_expected = op.src.stem
            if "_" in op.dst.stem:
                parts = op.dst.stem.split("_")
                if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) >= 2:
                    is_collision = True
                    num_collisions += 1

            if is_changed:
                num_changing += 1
                if is_collision:
                    new_item.setForeground(qcolor("warning"))
                else:
                    new_item.setForeground(qcolor("success"))
            else:
                new_item.setForeground(qcolor("text_secondary"))

            # 4. Date & source
            date_str = "—"
            if info and info.created:
                src_badge = f"[{info.created_source.upper()}]" if info.created_source else ""
                date_str = f"{info.created.strftime('%Y-%m-%d %H:%M')} {src_badge}"
            date_item = QTableWidgetItem(date_str)

            # 5. Resolution & Orientation
            dim_str = "—"
            if info:
                if info.width and info.height:
                    ori = "Ngang" if info.orientation == "H" else ("Dọc" if info.orientation == "V" else "")
                    dim_str = f"{info.width} × {info.height} ({ori})"
                elif info.duration:
                    mins = int(info.duration // 60)
                    secs = int(info.duration % 60)
                    dim_str = f"Video ({mins}:{secs:02d})"
            dim_item = QTableWidgetItem(dim_str)

            # 6. File size
            size_val = info.size if info else (op.src.stat().st_size if op.src.exists() else 0)
            size_item = QTableWidgetItem(_format_size(size_val))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # 7. Media type
            type_str = info.media_type.capitalize() if info else op.src.suffix.upper()
            ext_str = (info.extension if info else op.src.suffix).lstrip(".").upper()
            type_item = QTableWidgetItem(f"{ext_str} ({type_str})")

            # 8. Status
            if not is_changed:
                status_text = "Giữ nguyên"
                status_color = qcolor("text_secondary")
            elif is_collision:
                status_text = "Trùng tên (thêm hậu tố)"
                status_color = qcolor("warning")
            else:
                status_text = "Sẵn sàng đổi tên"
                status_color = qcolor("success")

            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(status_color)

            self.table.setItem(row, 0, folder_item)
            self.table.setItem(row, 1, old_item)
            self.table.setItem(row, 2, new_item)
            self.table.setItem(row, 3, date_item)
            self.table.setItem(row, 4, dim_item)
            self.table.setItem(row, 5, size_item)
            self.table.setItem(row, 6, type_item)
            self.table.setItem(row, 7, status_item)

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)

        # Update summary badges
        total_files = len(self.ops)
        num_folders = len(folders_seen)
        self.lbl_summary_files.setText(f"📁 {num_folders} thư mục | 📄 {total_files} tệp")
        self.lbl_summary_rename.setText(f"✏️ {num_changing} sẽ đổi tên")
        self.lbl_summary_collision.setText(f"⚠️ {num_collisions} trùng tên đã xử lý")

        self.lbl_status.setText(
            f"Tổng số: {total_files} tệp trong {num_folders} thư mục — {num_changing} tệp sẽ được đổi tên."
        )

        # Re-apply search filter if active
        if self.search_edit.text().strip():
            self._filter_table(self.search_edit.text())

    def _filter_table(self, text: str):
        """Filter visible rows based on search query."""
        query = text.strip().lower()
        visible_count = 0
        total_rows = self.table.rowCount()

        for row in range(total_rows):
            if not query:
                self.table.setRowHidden(row, False)
                visible_count += 1
                continue

            matches = False
            for col in (0, 1, 2, 3, 6):
                item = self.table.item(row, col)
                if item and query in item.text().lower():
                    matches = True
                    break

            self.table.setRowHidden(row, not matches)
            if matches:
                visible_count += 1

        if query:
            self.lbl_status.setText(f"Bộ lọc: Hiển thị {visible_count}/{total_rows} tệp phù hợp với '{query}'")

    def _copy_table_to_clipboard(self):
        """Export current preview table to clipboard in TSV format."""
        if not self.ops:
            return

        output = io.StringIO()
        writer = csv.writer(output, delimiter="\t")
        writer.writerow([
            "Thư mục con", "Tên gốc", "Tên mới dự kiến", "Ngày/EXIF",
            "Độ phân giải", "Dung lượng", "Định dạng", "Trạng thái",
        ])

        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            row_data = [
                (self.table.item(row, col).text() if self.table.item(row, col) else "")
                for col in range(self.table.columnCount())
            ]
            writer.writerow(row_data)

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(output.getvalue())
            QMessageBox.information(
                self, "Đã sao chép",
                "Danh sách bảng xem trước đã được sao chép vào Clipboard (dạng bảng TSV)!"
            )

    def eventFilter(self, obj, event):
        """Handle mouse hover over table rows to display HoverThumbnailPopup."""
        if obj == self.table.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint()
                item = self.table.itemAt(pos)
                if item:
                    row = item.row()
                    if 0 <= row < len(self.ops):
                        op = self.ops[row]
                        info = self._last_info_by_path.get(op.src)
                        meta_parts = []
                        if info:
                            if info.width and info.height:
                                ori = "Ngang" if info.orientation == "H" else "Dọc"
                                meta_parts.append(f"{info.width}×{info.height} ({ori})")
                            if info.created:
                                meta_parts.append(info.created.strftime('%Y-%m-%d %H:%M'))
                            meta_parts.append(_format_size(info.size))
                        meta_str = " • ".join(meta_parts)
                        HoverThumbnailPopup.instance().show_preview(
                            op.src, event.globalPosition().toPoint(), meta_str
                        )
                else:
                    HoverThumbnailPopup.instance().hide()
            elif event.type() == QEvent.Type.Leave:
                HoverThumbnailPopup.instance().hide()
        return super().eventFilter(obj, event)

    # ─────────────────────────────────────────────
    # Execution
    # ─────────────────────────────────────────────

    def _execute(self):
        if not self.ops:
            QMessageBox.information(self, "Thông báo", "Không có tệp nào để đổi tên.")
            return

        num_changing = sum(1 for op in self.ops if op.src.name != op.dst.name)
        reply = QMessageBox.question(
            self, "Xác nhận đổi tên",
            f"Bạn có chắc chắn muốn đổi tên {num_changing}/{len(self.ops)} tệp qua cây thư mục?\n\n"
            f"• Cấu trúc thư mục con của từng tệp sẽ được giữ nguyên hoàn toàn.\n"
            f"• Thao tác này CÓ THỂ KHÔI PHỤC an toàn qua file nhật ký (Log).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Switch dry run to false
        for op in self.ops:
            op.dry_run = False

        self.btn_execute.setEnabled(False)
        self.btn_preview.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang đổi tên tệp...", parent=self)
        self._progress_dlg.set_task("Đang đổi tên tệp...", total=len(self.ops), icon="✏️")

        # Prepare logger to run concurrently in the background thread
        log_path_str = self.log_path_edit.text().strip()
        self._current_log_path = Path(log_path_str) if log_path_str else Path("rename_log.jsonl")
        logger = RenameLogger(self._current_log_path, compute_checksums=self.chk_checksum.isChecked())

        self._rename_worker = RenameWorker(ops=self.ops, logger=logger)
        self._rename_thread = QThread(self)
        self._rename_worker.moveToThread(self._rename_thread)
        self._rename_thread.started.connect(self._rename_worker.run)

        self._progress_dlg.attach_worker(self._rename_worker)
        self._progress_dlg.cancelled.connect(self._rename_worker.cancel, Qt.ConnectionType.DirectConnection)
        self._rename_worker.progress.connect(self._progress_dlg.update_progress)
        self._rename_worker.progress.connect(self._on_rename_progress)
        self._rename_worker.finished.connect(self._on_rename_finished)
        self._rename_worker.cancelled.connect(self._on_rename_cancelled)
        self._rename_worker.error.connect(self._on_rename_error)

        self._progress_dlg.show_centered()
        self._rename_thread.start()

    def _on_rename_progress(self, done: int, total: int, name: str):
        self.lbl_status.setText(f"Đang đổi tên: {name}  ({done}/{total})")

    def _on_rename_finished(self, ops: list):
        if self._rename_thread and self._rename_thread.isRunning():
            self._rename_thread.quit()
            self._rename_thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn thành đổi tên!")

        self.btn_cancel.setText("Đóng")
        self.btn_preview.setEnabled(True)

        log_path = getattr(self, "_current_log_path", Path("rename_log.jsonl"))

        # Update table rows with result status (wrapped in setUpdatesEnabled to prevent GUI lag)
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            for row, op in enumerate(ops):
                if row < self.table.rowCount():
                    item = self.table.item(row, 7)
                    if item:
                        if op.error:
                            item.setText(f"Lỗi: {op.error}")
                            item.setForeground(qcolor("danger"))
                        elif op.src.name != op.dst.name:
                            item.setText("✅ Đã đổi tên")
                            item.setForeground(qcolor("success"))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        errors = [op for op in ops if op.error]
        if errors:
            err_msg = "\n".join(f"- {op.src.name}: {op.error}" for op in errors[:5])
            if len(errors) > 5:
                err_msg += f"\n... và {len(errors)-5} tệp nữa"
            QMessageBox.warning(
                self, "Hoàn thành với lỗi",
                f"Đổi tên hoàn thành. {len(errors)}/{len(ops)} tệp gặp lỗi:\n{err_msg}\n\n"
                f"File log: {log_path}"
            )
        else:
            QMessageBox.information(
                self, "Thành công",
                f"Đã đổi tên thành công {len(ops)} tệp xuyên suốt cây thư mục!\n"
                f"File nhật ký: {log_path}"
            )
            self.lbl_status.setText(f"✅ Hoàn thành xuất sắc! Đã đổi {len(ops)} tệp. Log: {log_path}")

        self.rename_completed.emit(ops)

    def _on_rename_cancelled(self):
        if self._rename_thread and self._rename_thread.isRunning():
            self._rename_thread.quit()
            self._rename_thread.wait(300)
        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng thao tác bởi người dùng.")
        self.btn_execute.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.lbl_status.setText("⚠️ Thao tác đổi tên đã bị hủy bởi người dùng.")

        # Update table rows with result status for executed vs cancelled ops
        ops = getattr(self, "ops", [])
        if hasattr(self, "_rename_worker") and self._rename_worker and hasattr(self._rename_worker, "ops"):
            ops = self._rename_worker.ops

        executed_ops = []
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            for row, op in enumerate(ops):
                if row < self.table.rowCount():
                    item = self.table.item(row, 7)
                    if item:
                        if op.error:
                            item.setText(f"Lỗi: {op.error}")
                            item.setForeground(qcolor("danger"))
                        elif getattr(op, "executed", False) and op.src.name != op.dst.name:
                            item.setText("✅ Đã đổi tên")
                            item.setForeground(qcolor("success"))
                            executed_ops.append(op)
                        elif not getattr(op, "executed", False):
                            item.setText("⚠️ Đã hủy")
                            item.setForeground(qcolor("warning"))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if executed_ops:
            self.rename_completed.emit(executed_ops)

        QMessageBox.information(
            self, "Đã hủy",
            f"Đã dừng tiến trình đổi tên theo yêu cầu của bạn.\n"
            f"Đã đổi {len(executed_ops)}/{len(ops)} tệp trước khi dừng."
        )

    def _on_rename_error(self, err_msg: str):
        if self._rename_thread and self._rename_thread.isRunning():
            self._rename_thread.quit()
            self._rename_thread.wait(300)
        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()
        self.btn_execute.setEnabled(True)
        self.btn_preview.setEnabled(True)
        QMessageBox.critical(self, "Lỗi khi đổi tên", f"Đã xảy ra lỗi: {err_msg}")

    def _browse_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Chọn đường dẫn file log", "",
            "JSON Lines (*.jsonl);;All Files (*)"
        )
        if path:
            self.log_path_edit.setText(path)

    # ─────────────────────────────────────────────
    # State Persistence
    # ─────────────────────────────────────────────

    def _save_settings(self):
        try:
            settings = QSettings("FileManagerPro", "RenameDialog")
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("date_fmt", self.date_fmt_combo.currentText())
            settings.setValue("pattern", self.pattern_edit.text())
            col_widths = [self.table.columnWidth(c) for c in range(self.table.columnCount())]
            settings.setValue("column_widths", col_widths)
        except Exception:
            pass

    def _load_settings(self):
        try:
            settings = QSettings("FileManagerPro", "RenameDialog")
            geom = settings.value("geometry")
            if geom:
                self.restoreGeometry(geom)
            fmt = settings.value("date_fmt")
            if fmt and fmt in ["DDMMYY", "DDMMYYYY", "YYYYMMDD", "MMDDYY"]:
                self.date_fmt_combo.setCurrentText(fmt)
            pat = settings.value("pattern")
            if pat:
                self.pattern_edit.setText(pat)
            widths = settings.value("column_widths")
            if widths and isinstance(widths, list):
                for c, w in enumerate(widths):
                    if c < self.table.columnCount() and int(w) > 30:
                        self.table.setColumnWidth(c, int(w))
        except Exception:
            pass

    def closeEvent(self, event):
        """Safely stop background threads and save settings upon dialog closure."""
        HoverThumbnailPopup.instance().hide()
        self._cancel_scan()
        self._cleanup_scan_thread()
        self._save_settings()
        if self._rename_thread and self._rename_thread.isRunning():
            self._rename_thread.quit()
            self._rename_thread.wait(300)
        super().closeEvent(event)

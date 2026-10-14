"""
ui/panels/right_dock_panel.py
Dual-Mode Right Panel:
- Normal Mode (Default): Full-featured PreviewPanel (photo/video preview, EXIF, metadata).
- Queue Mode (On-demand): Sequential Drag-and-Drop Queue Dock with live thumbnail slots,
  automatic number ordering [Số thứ tự]_[Tên cũ], quick-sort tools, and direct execution.

The user can freely switch between normal preview and queue dock, or trigger queue mode
from the toolbar / context menu.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QMimeData, QThread
from PyQt6.QtGui import QPixmap, QIcon, QFont, QColor, QImageReader, QDrag, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QComboBox, QMessageBox,
    QFrame, QSizePolicy, QToolButton,
)

from ui.panels.preview_panel import PreviewPanel
from core.scanner import FileInfo, DirectoryScanner
from core.renamer import build_new_name, RenameEngine
from core.logger import RenameLogger
from core.workers import RenameWorker
from utils.file_utils import RenameOperation, IMAGE_EXTS, VIDEO_EXTS
from ui.widgets.progress_dialog import TaskProgressDialog


class QueueDropTable(QTableWidget):
    """
    Drop-enabled table for queue slots.
    Accepts files dragged from ContentPanel or external file explorer.
    """
    files_dropped = pyqtSignal(list)  # list[Path]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setStyleSheet(
            "QTableWidget { background-color: #1c1c1e; gridline-color: #2c2c2e; "
            "border: 1px solid #3a3a3c; border-radius: 6px; }"
            "QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #28282a; }"
            "QTableWidget::item:selected { background-color: #0a84ff; color: white; }"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths: list[Path] = []
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.is_file():
                    paths.append(p)
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            for line in text.splitlines():
                p = Path(line.strip().strip('"'))
                if p.is_file():
                    paths.append(p)

        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class AsyncThumbnailWorker(QThread):
    """Asynchronously decodes thumbnails in background so main GUI thread never freezes."""
    thumbnail_ready = pyqtSignal(Path, QPixmap)

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = paths
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for p in self.paths:
            if self._cancelled:
                break
            ext = p.suffix.lower()
            if ext in IMAGE_EXTS:
                try:
                    with open(p, "rb") as f:
                        data = f.read()
                    img = QImage()
                    if img.loadFromData(data):
                        img = img.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if not img.isNull() and not self._cancelled:
                            pix = QPixmap.fromImage(img)
                            self.thumbnail_ready.emit(p, pix)
                except Exception:
                    pass


class FolderScanThread(QThread):
    """Background thread to scan all files in folder without blocking GUI."""
    scan_finished = pyqtSignal(list)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        try:
            scanner = DirectoryScanner(root=self.folder, recursive=False, max_workers=8)
            files = scanner.scan()
            self.scan_finished.emit(files)
        except Exception:
            self.scan_finished.emit([])


class QueueDockWidget(QWidget):
    """
    The Queue Dock view embedded on the right panel.
    Acts as the destination for files dragged from the central 'Kho' (ContentPanel).
    """
    file_selected = pyqtSignal(Path)
    queue_completed = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_folder: Optional[Path] = None
        self.queue_items: list[FileInfo] = []  # Ordered list of items
        self._thumb_cache: dict[Path, QPixmap] = {}
        self._attempted_paths: set[Path] = set()
        self._thumb_worker: Optional[AsyncThumbnailWorker] = None
        self._scan_thread: Optional[FolderScanThread] = None
        self._worker: Optional[RenameWorker] = None
        self._thread: Optional[QThread] = None

        self._placeholder_pix = QPixmap(36, 36)
        self._placeholder_pix.fill(QColor("#2c2c2e"))

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── Header: Title & Close Button ──
        hdr_bar = QHBoxLayout()
        lbl_title = QLabel("🔢 Hàng đợi Đổi tên (Kéo thả)")
        lbl_title.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #0a84ff;")
        hdr_bar.addWidget(lbl_title)
        hdr_bar.addStretch()

        btn_close = QPushButton("✕ Đóng")
        btn_close.setToolTip("Quay lại chế độ Xem trước thông thường")
        btn_close.setFixedHeight(24)
        btn_close.setStyleSheet(
            "QPushButton { background: #3a3a3c; color: #d1d1d6; border-radius: 4px; "
            "padding: 2px 8px; font-size: 8.5pt; font-weight: 600; border: none; }"
            "QPushButton:hover { background: #48484a; color: white; }"
        )
        btn_close.clicked.connect(self.close_requested.emit)
        hdr_bar.addWidget(btn_close)
        layout.addLayout(hdr_bar)

        # ── Settings Bar: STT Format ──
        cfg_bar = QHBoxLayout()
        cfg_bar.addWidget(QLabel("Định dạng STT:"))
        self.combo_digits = QComboBox()
        self.combo_digits.addItems(["3 chữ số (001...)", "2 chữ số (01...)", "1, 2, 3..."])
        self.combo_digits.currentIndexChanged.connect(self._refresh_table)
        cfg_bar.addWidget(self.combo_digits)
        cfg_bar.addStretch()
        layout.addLayout(cfg_bar)

        # ── Quick Actions Row ──
        act_bar = QHBoxLayout()
        self.btn_load_all = QPushButton("➕ Nạp tất cả tệp")
        self.btn_load_all.setToolTip("Nạp toàn bộ tệp trong thư mục đang mở vào hàng đợi")
        self.btn_load_all.setStyleSheet(
            "QPushButton { background: #2c2c2e; color: #0a84ff; border: 1px solid #3a3a3c; "
            "border-radius: 4px; padding: 3px 6px; font-size: 8pt; font-weight: 600; }"
            "QPushButton:hover { background: #3a3a3c; }"
        )
        self.btn_load_all.clicked.connect(self.load_all_from_current_folder)
        act_bar.addWidget(self.btn_load_all)

        btn_sort_date = QPushButton("⚡ Ngày")
        btn_sort_date.setToolTip("Tự động sắp xếp theo ngày chụp/tạo cũ → mới")
        btn_sort_date.setStyleSheet(self.btn_load_all.styleSheet())
        btn_sort_date.clicked.connect(self._sort_by_date)
        act_bar.addWidget(btn_sort_date)

        btn_sort_name = QPushButton("⚡ Tên A-Z")
        btn_sort_name.setToolTip("Sắp xếp theo tên A-Z")
        btn_sort_name.setStyleSheet(self.btn_load_all.styleSheet())
        btn_sort_name.clicked.connect(self._sort_by_name)
        act_bar.addWidget(btn_sort_name)

        btn_clear = QPushButton("↺ Xóa")
        btn_clear.setToolTip("Làm trống hàng đợi")
        btn_clear.setStyleSheet(
            "QPushButton { background: #2c2c2e; color: #ff453a; border: 1px solid #3a3a3c; "
            "border-radius: 4px; padding: 3px 6px; font-size: 8pt; font-weight: 600; }"
            "QPushButton:hover { background: #3a3a3c; }"
        )
        btn_clear.clicked.connect(self.clear_queue)
        act_bar.addWidget(btn_clear)

        layout.addLayout(act_bar)

        # ── Drop hint ──
        self.lbl_hint = QLabel("💡 Kéo thả tệp từ Bảng giữa (Kho) vào đây")
        self.lbl_hint.setStyleSheet("color: #8e8e93; font-size: 8pt; font-style: italic;")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_hint)

        # ── Queue Slots Table ──
        self.table = QueueDropTable()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["STT", "Xem trước", "Tên mới dự kiến", "Thao tác"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.files_dropped.connect(self.add_paths)
        self.table.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.table)

        # ── Bottom Status & Execution ──
        self.lbl_summary = QLabel("0 tệp trong hàng đợi")
        self.lbl_summary.setStyleSheet("color: #8e8e93; font-size: 8.5pt;")
        layout.addWidget(self.lbl_summary)

        self.btn_execute = QPushButton("✔ Thực hiện Đổi tên Hàng đợi")
        self.btn_execute.setObjectName("btnPrimary")
        self.btn_execute.setFixedHeight(34)
        self.btn_execute.setEnabled(False)
        self.btn_execute.setStyleSheet(
            "QPushButton { background: #0a84ff; color: white; font-weight: 700; "
            "font-size: 9pt; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #0071e3; }"
            "QPushButton:disabled { background: #3a3a3c; color: #636366; }"
        )
        self.btn_execute.clicked.connect(self._execute_rename)
        layout.addWidget(self.btn_execute)

    def set_folder(self, folder: Path):
        """Update current folder context."""
        self.current_folder = folder
        self.btn_load_all.setEnabled(folder is not None and folder.is_dir())

    def add_paths(self, paths: list[Path]):
        """Add file paths into the queue, avoiding duplicates."""
        existing_paths = {f.path for f in self.queue_items}
        new_paths = [p for p in paths if p not in existing_paths and p.is_file()]
        if not new_paths:
            return

        scanner = DirectoryScanner(root=new_paths[0].parent, recursive=False, max_workers=8)
        infos = scanner.scan_paths(new_paths)
        for info in infos:
            self.queue_items.append(info)

        self._refresh_table()

    def load_all_from_current_folder(self, sync: bool = False):
        """Populate all media/files directly inside the current folder (async by default)."""
        if not self.current_folder or not self.current_folder.is_dir():
            return
        if sync:
            scanner = DirectoryScanner(root=self.current_folder, recursive=False, max_workers=8)
            files = scanner.scan()
            self._on_folder_scan_finished(files)
            return

        if self._scan_thread and self._scan_thread.isRunning():
            return

        self.btn_load_all.setEnabled(False)
        self.lbl_summary.setText("⏳ Đang nạp danh sách tệp...")

        self._scan_thread = FolderScanThread(self.current_folder, self)
        self._scan_thread.scan_finished.connect(self._on_folder_scan_finished)
        self._scan_thread.start()

    def _on_folder_scan_finished(self, files: list):
        self.btn_load_all.setEnabled(True)
        if not files:
            QMessageBox.information(self, "Thông báo", "Không tìm thấy tệp nào trong thư mục này.")
            self.lbl_summary.setText("0 tệp trong hàng đợi")
            return

        self.queue_items = list(files)
        self._refresh_table()

    def clear_queue(self):
        """Clear all items in queue."""
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()
            self._thumb_worker.wait(1000)
        self.queue_items.clear()
        self._attempted_paths.clear()
        self._refresh_table()

    def _sort_by_date(self):
        """Sort queue items by capture/creation date ascending."""
        from datetime import datetime
        self.queue_items.sort(key=lambda f: (f.created or f.modified or datetime.min))
        self._refresh_table()

    def _sort_by_name(self):
        """Sort queue items by original file name."""
        self.queue_items.sort(key=lambda f: f.path.name.lower())
        self._refresh_table()

    def _format_seq(self, index: int) -> str:
        idx_combo = self.combo_digits.currentIndex()
        if idx_combo == 0:
            return f"{index + 1:03d}"
        elif idx_combo == 1:
            return f"{index + 1:02d}"
        else:
            return f"{index + 1}"

    def _refresh_table(self):
        """Re-render table rows instantly with updated numbering and planned names."""
        n = len(self.queue_items)
        self.table.setRowCount(n)
        self.lbl_summary.setText(f"{n} tệp trong hàng đợi")
        self.btn_execute.setEnabled(n > 0)
        self.lbl_hint.setVisible(n == 0)

        uncached_paths: list[Path] = []

        for i, info in enumerate(self.queue_items):
            seq_str = self._format_seq(i)
            planned_name = f"{seq_str}_{info.path.name}"

            # 1. STT Badge
            item_seq = QTableWidgetItem(f" #{seq_str} ")
            item_seq.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_seq.setForeground(QColor("#0a84ff"))
            font = item_seq.font()
            font.setBold(True)
            item_seq.setFont(font)
            self.table.setItem(i, 0, item_seq)

            # 2. Thumbnail (Instant from cache or placeholder)
            item_thumb = QTableWidgetItem()
            if info.path in self._thumb_cache:
                pix = self._thumb_cache[info.path]
            else:
                pix = self._placeholder_pix
                if info.path.suffix.lower() in IMAGE_EXTS and info.path not in self._attempted_paths:
                    uncached_paths.append(info.path)
                    self._attempted_paths.add(info.path)
            item_thumb.setIcon(QIcon(pix))
            item_thumb.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 1, item_thumb)

            # 3. Planned Name
            item_name = QTableWidgetItem(planned_name)
            item_name.setToolTip(f"Tên gốc: {info.path.name}\nĐường dẫn: {info.path}")
            self.table.setItem(i, 2, item_name)

            # 4. Action Buttons (▲, ▼, ✖)
            act_widget = QWidget()
            act_lay = QHBoxLayout(act_widget)
            act_lay.setContentsMargins(2, 2, 2, 2)
            act_lay.setSpacing(3)

            btn_up = QToolButton()
            btn_up.setText("▲")
            btn_up.setToolTip("Di chuyển lên")
            btn_up.setEnabled(i > 0)
            btn_up.setFixedSize(20, 20)
            btn_up.clicked.connect(lambda _, row=i: self._move_item(row, -1))
            act_lay.addWidget(btn_up)

            btn_dn = QToolButton()
            btn_dn.setText("▼")
            btn_dn.setToolTip("Di chuyển xuống")
            btn_dn.setEnabled(i < n - 1)
            btn_dn.setFixedSize(20, 20)
            btn_dn.clicked.connect(lambda _, row=i: self._move_item(row, 1))
            act_lay.addWidget(btn_dn)

            btn_rm = QToolButton()
            btn_rm.setText("✖")
            btn_rm.setToolTip("Xóa khỏi hàng đợi")
            btn_rm.setFixedSize(20, 20)
            btn_rm.setStyleSheet("color: #ff453a;")
            btn_rm.clicked.connect(lambda _, row=i: self._remove_item(row))
            act_lay.addWidget(btn_rm)

            self.table.setCellWidget(i, 3, act_widget)
            self.table.setRowHeight(i, 40)

        # Trigger background thumbnail decoding
        if uncached_paths:
            self._start_async_thumbnails(uncached_paths)

    def _start_async_thumbnails(self, paths: list[Path]):
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()
            self._thumb_worker.wait(100)
        self._thumb_worker = AsyncThumbnailWorker(paths, self)
        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_worker.start()

    def _on_thumbnail_ready(self, path: Path, pix: QPixmap):
        self._thumb_cache[path] = pix
        for row, info in enumerate(self.queue_items):
            if info.path == path:
                item = self.table.item(row, 1)
                if item:
                    item.setIcon(QIcon(pix))
                break

    def _move_item(self, row: int, delta: int):
        target = row + delta
        if 0 <= target < len(self.queue_items):
            self.queue_items[row], self.queue_items[target] = self.queue_items[target], self.queue_items[row]
            self._refresh_table()
            self.table.selectRow(target)

    def _remove_item(self, row: int):
        if 0 <= row < len(self.queue_items):
            self.queue_items.pop(row)
            self._refresh_table()

    def _on_item_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if 0 <= row < len(self.queue_items):
            self.file_selected.emit(self.queue_items[row].path)

    def _execute_rename(self):
        """Perform sequential renaming with WAL logging, worker thread, and popup progress dialog."""
        n = len(self.queue_items)
        if n == 0:
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận đổi tên hàng đợi",
            f"Bạn có chắc chắn muốn đổi tên {n} tệp theo đúng thứ tự hàng đợi đã sắp xếp?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Prepare operations
        ops: list[RenameOperation] = []
        for i, info in enumerate(self.queue_items):
            seq_str = self._format_seq(i)
            new_name = f"{seq_str}_{info.path.name}"
            dest = info.path.parent / new_name
            ops.append(RenameOperation(src=info.path, dst=dest, dry_run=False, original_name=info.path.name))

        self.btn_execute.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang đổi tên hàng đợi...", parent=self.window())
        self._progress_dlg.set_task("Đang đổi tên hàng đợi...", total=len(ops), icon="🔢")

        # Same log as QueueRenameDialog so the Restore dialog can undo dock renames too
        logger = RenameLogger(Path("rename_log.jsonl"))
        self._worker = RenameWorker(ops=ops, logger=logger)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.finished.connect(self._on_rename_finished)
        self._worker.cancelled.connect(self._on_rename_cancelled)
        self._worker.error.connect(self._on_rename_error)

        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_rename_finished(self, ops: list[RenameOperation]):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn thành đổi tên hàng đợi!")

        self.btn_execute.setEnabled(True)

        success_ops = [op for op in ops if not op.error]
        failed_ops = [op for op in ops if op.error]

        if failed_ops:
            QMessageBox.warning(
                self,
                "Hoàn thành có lỗi",
                f"Đã đổi tên {len(success_ops)} tệp thành công.\nCó {len(failed_ops)} tệp thất bại.",
            )
        else:
            QMessageBox.information(
                self,
                "Thành công",
                f"Đã đổi tên thành công toàn bộ {len(success_ops)} tệp theo đúng thứ tự hàng đợi!",
            )

        self.clear_queue()
        self.queue_completed.emit()

    def _on_rename_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng thao tác bởi người dùng.")

        self.btn_execute.setEnabled(True)
        executed_ops = [op for op in getattr(self._worker, "ops", []) if getattr(op, "executed", False)]
        if executed_ops:
            self.queue_completed.emit()
            QMessageBox.information(
                self,
                "Đã hủy",
                f"Đã dừng tiến trình đổi tên hàng đợi theo yêu cầu của bạn.\n"
                f"Đã đổi {len(executed_ops)}/{len(getattr(self._worker, 'ops', []))} tệp trước khi dừng.",
            )
        else:
            QMessageBox.information(
                self,
                "Đã hủy",
                "Đã dừng tiến trình đổi tên hàng đợi theo yêu cầu của bạn.",
            )

    def _on_rename_error(self, err_msg: str):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_execute.setEnabled(True)
        QMessageBox.critical(self, "Lỗi thực thi", f"Quá trình đổi tên gặp lỗi:\n{err_msg}")


class RightDockPanel(QWidget):
    """
    Combined Right-hand Panel:
    - Page 0 (Default): Standard PreviewPanel (Full preview, EXIF, metadata).
    - Page 1: QueueDockWidget (Sequential drag-and-drop queue with preview thumbnails).

    Allows switching easily between normal preview mode and queue mode.
    """
    file_preview_requested = pyqtSignal(Path)
    queue_completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top Segmented Pill Header ──
        top_bar = QWidget()
        top_bar.setStyleSheet("background: #242426; border-bottom: 1px solid #3a3a3c;")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(4)

        self.btn_mode_preview = QPushButton("👁️ Xem trước")
        self.btn_mode_preview.setCheckable(True)
        self.btn_mode_preview.setChecked(True)
        self.btn_mode_preview.setToolTip("Xem trước chi tiết ảnh/video, thông số EXIF")

        self.btn_mode_queue = QPushButton("🔢 Hàng đợi Đổi tên")
        self.btn_mode_queue.setCheckable(True)
        self.btn_mode_queue.setChecked(False)
        self.btn_mode_queue.setToolTip("Mở dãy hàng đợi kéo thả đánh số thứ tự")

        for btn in (self.btn_mode_preview, self.btn_mode_queue):
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { background: transparent; color: #8e8e93; border: 1px solid transparent; "
                "border-radius: 5px; padding: 2px 10px; font-size: 8.5pt; font-weight: 600; }"
                "QPushButton:checked { background: #3a3a3c; color: #0a84ff; border-color: #0a84ff; }"
                "QPushButton:hover:!checked { background: #2c2c2e; color: #d1d1d6; }"
            )
            tb_layout.addWidget(btn)

        self.btn_mode_preview.clicked.connect(lambda: self.set_mode("preview"))
        self.btn_mode_queue.clicked.connect(lambda: self.set_mode("queue"))

        layout.addWidget(top_bar)

        # ── Stack: Page 0 (Preview), Page 1 (Queue) ──
        self.stack = QStackedWidget()

        self.preview_panel = PreviewPanel(self)
        self.stack.addWidget(self.preview_panel)  # Index 0

        self.queue_dock = QueueDockWidget(self)
        self.queue_dock.close_requested.connect(lambda: self.set_mode("preview"))
        self.queue_dock.file_selected.connect(self._on_queue_item_selected)
        self.queue_dock.queue_completed.connect(self.queue_completed.emit)
        self.stack.addWidget(self.queue_dock)     # Index 1

        layout.addWidget(self.stack)

    def set_mode(self, mode: str):
        """Switch between 'preview' and 'queue' modes."""
        if mode == "queue":
            self.stack.setCurrentIndex(1)
            self.btn_mode_preview.setChecked(False)
            self.btn_mode_queue.setChecked(True)
        else:
            self.stack.setCurrentIndex(0)
            self.btn_mode_preview.setChecked(True)
            self.btn_mode_queue.setChecked(False)

    def is_queue_mode(self) -> bool:
        return self.stack.currentIndex() == 1

    def show_file(self, path: Path):
        """Pass selected file to PreviewPanel (and optionally highlight in queue)."""
        self.preview_panel.show_file(path)

    def _on_queue_item_selected(self, path: Path):
        """When user clicks an item in the queue dock, show preview."""
        self.preview_panel.show_file(path)
        self.file_preview_requested.emit(path)

    def set_folder(self, folder: Path):
        """Sync folder with QueueDockWidget."""
        self.queue_dock.set_folder(folder)

    def open_queue_with_folder(self, folder: Path, sync: bool = False):
        """Directly open queue mode and load all files in folder."""
        self.set_folder(folder)
        self.set_mode("queue")
        self.queue_dock.load_all_from_current_folder(sync=sync)

    def open_queue_with_paths(self, paths: list[Path]):
        """Directly open queue mode and populate specified paths."""
        if paths:
            self.set_folder(paths[0].parent)
        self.set_mode("queue")
        self.queue_dock.add_paths(paths)

"""
ui/dialogs/queue_rename_dialog.py
Drag-and-Drop Sequential Queue Renamer.
Features:
- Left panel: Source pool of N files in folder with thumbnails, resolution, and date.
- Right panel: Ordered queue of N numbered slots (#01 .. #N).
- Drag-and-drop or double-click to assign files into slots.
- Drag-reorder or up/down/remove controls.
- Auto-sort buttons (by EXIF date, name, resolution).
- Renaming formula: [Số thứ tự]_[Tên theo quy tắc cũ].
- Safe execution with WAL logging.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QThread, pyqtSignal, QSize, QMimeData, QPoint
from PyQt6.QtGui   import QColor, QFont, QPixmap, QImageReader, QDrag
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QGroupBox, QMessageBox, QHeaderView,
    QAbstractItemView, QWidget, QSplitter, QFrame,
    QListWidget, QListWidgetItem,
)

from core.scanner  import FileInfo, DirectoryScanner
from core.renamer  import build_new_name
from core.logger   import RenameLogger
from core.workers  import RenameWorker
from utils.file_utils import RenameOperation, IMAGE_EXTS, VIDEO_EXTS
from ui.widgets.progress_dialog import TaskProgressDialog


class SourcePoolList(QListWidget):
    """Left side list of unassigned files supporting drag initiation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet(
            "QListWidget { background-color: #1c1c1e; border: 1px solid #3a3a3c; "
            "border-radius: 6px; padding: 4px; }"
            "QListWidget::item { padding: 6px; border-bottom: 1px solid #2c2c2e; border-radius: 4px; }"
            "QListWidget::item:hover { background-color: #2c2c2e; }"
            "QListWidget::item:selected { background-color: #0a84ff; color: white; }"
        )

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(path_str)
        drag.setMimeData(mime)

        pixmap = item.icon().pixmap(48, 48)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(24, 24))

        drag.exec(Qt.DropAction.MoveAction)


class QueueTableWidget(QTableWidget):
    """Right side table of N numbered slots supporting drop from source pool."""
    file_dropped = pyqtSignal(int, Path)  # (row_index, file_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setStyleSheet(
            "QTableWidget { background-color: #1c1c1e; gridline-color: #2c2c2e; "
            "border: 1px solid #3a3a3c; border-radius: 6px; }"
            "QTableWidget::item { padding: 4px 6px; }"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path_str = event.mimeData().text().strip()
        if path_str:
            pos = event.position().toPoint()
            row = self.rowAt(pos.y())
            if row >= 0:
                self.file_dropped.emit(row, Path(path_str))
                event.acceptProposedAction()
                return
        event.ignore()


class QueueRenameDialog(QDialog):
    """
    Drag-and-Drop Sequential Queue Renamer:
    Allows user to place N files into an exact order and rename them with
    sequential number prefix: [Số thứ tự]_[Quy tắc cũ].
    """
    rename_completed = pyqtSignal(list)

    def __init__(
        self,
        folder: Path,
        files: Optional[list[FileInfo]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.folder = folder
        self.files: list[FileInfo] = []
        self.info_by_path: dict[Path, FileInfo] = {}

        # Slots data: list of Optional[FileInfo], length N
        self.slots: list[Optional[FileInfo]] = []
        self.total_count = 0

        # Threading for execution
        self._thread: Optional[QThread] = None
        self._worker: Optional[RenameWorker] = None

        self.setWindowTitle(f"Đổi tên theo Hàng đợi Kéo-Thả (Số thứ tự) — {self.folder.name}")
        self.resize(1180, 700)
        self.setMinimumSize(960, 580)

        self._load_files(files)
        self._build_ui()
        self._populate_all()

    def _load_files(self, pre_files: Optional[list[FileInfo]] = None):
        """Gather all media/files directly inside self.folder."""
        if pre_files:
            self.files = [f for f in pre_files if f.path.parent == self.folder]
        else:
            scanner = DirectoryScanner(root=self.folder, recursive=False, max_workers=8)
            self.files = scanner.scan()

        self.info_by_path = {f.path: f for f in self.files}
        self.total_count = len(self.files)
        self.slots = [None] * self.total_count

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # ── Header bar: Title & Configuration ──
        header_group = QGroupBox(f"📁 Thư mục: {self.folder.name} ({self.total_count} tệp)")
        header_group.setStyleSheet(
            "QGroupBox { font-weight: 600; font-size: 9pt; border: 1px solid #3a3a3c; "
            "border-radius: 6px; margin-top: 8px; padding-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        hg_layout = QHBoxLayout(header_group)
        hg_layout.setContentsMargins(10, 6, 10, 6)
        hg_layout.setSpacing(10)

        hg_layout.addWidget(QLabel("Định dạng số TT:"))
        self.combo_digits = QComboBox()
        self.combo_digits.addItems(["3 chữ số (001, 002...)", "2 chữ số (01, 02...)", "Số tự nhiên (1, 2...)"])
        self.combo_digits.currentIndexChanged.connect(self._refresh_queue_display)
        hg_layout.addWidget(self.combo_digits)

        hg_layout.addWidget(QLabel("  Định dạng ngày:"))
        self.combo_date_fmt = QComboBox()
        self.combo_date_fmt.addItems(["DDMMYY", "DDMMYYYY", "YYYYMMDD", "MMDDYY"])
        self.combo_date_fmt.currentTextChanged.connect(self._refresh_queue_display)
        hg_layout.addWidget(self.combo_date_fmt)

        hg_layout.addStretch()

        # Quick auto-sort buttons
        btn_sort_date_asc = QPushButton("⚡ Ngày chụp (Cũ → Mới)")
        btn_sort_date_asc.setToolTip("Tự động điền hàng đợi theo thời gian chụp ảnh/tạo tệp từ cũ nhất đến mới nhất")
        btn_sort_date_asc.clicked.connect(lambda: self._auto_sort("date_asc"))
        hg_layout.addWidget(btn_sort_date_asc)

        btn_sort_date_desc = QPushButton("⚡ Ngày chụp (Mới → Cũ)")
        btn_sort_date_desc.clicked.connect(lambda: self._auto_sort("date_desc"))
        hg_layout.addWidget(btn_sort_date_desc)

        btn_sort_name = QPushButton("⚡ Tên A-Z")
        btn_sort_name.clicked.connect(lambda: self._auto_sort("name"))
        hg_layout.addWidget(btn_sort_name)

        btn_reset = QPushButton("↺ Đặt lại")
        btn_reset.setToolTip("Xóa toàn bộ hàng đợi và đưa tất cả tệp về kho gốc bên trái")
        btn_reset.clicked.connect(self._reset_queue)
        hg_layout.addWidget(btn_reset)

        root_layout.addWidget(header_group)

        # ── Main 2-column Splitter ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Column: Source Pool
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.lbl_pool_count = QLabel("📦 Kho tệp nguồn (Kéo hoặc Double-click để xếp):")
        self.lbl_pool_count.setStyleSheet("font-weight: 600; color: #8e8e93; font-size: 8.5pt;")
        left_layout.addWidget(self.lbl_pool_count)

        self.pool_search = QLineEdit()
        self.pool_search.setPlaceholderText("🔍 Tìm trong kho nguồn...")
        self.pool_search.setClearButtonEnabled(True)
        self.pool_search.textChanged.connect(self._filter_pool)
        left_layout.addWidget(self.pool_search)

        self.pool_list = SourcePoolList()
        self.pool_list.itemDoubleClicked.connect(self._on_pool_double_clicked)
        left_layout.addWidget(self.pool_list)

        btn_fill_all = QPushButton("⏩ Điền tất cả vào các vị trí trống còn lại")
        btn_fill_all.clicked.connect(self._fill_remaining_slots)
        left_layout.addWidget(btn_fill_all)

        splitter.addWidget(left_widget)

        # Right Column: Ordered Queue
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.lbl_queue_count = QLabel(f"🔢 Hàng đợi thứ tự ({self.total_count} vị trí):")
        self.lbl_queue_count.setStyleSheet("font-weight: 600; color: #5ac8fa; font-size: 8.5pt;")
        right_layout.addWidget(self.lbl_queue_count)

        self.queue_table = QueueTableWidget()
        self.queue_table.file_dropped.connect(self._on_file_dropped)
        self.queue_table.setColumnCount(4)
        self.queue_table.setHorizontalHeaderLabels([
            "Vị trí (Số TT)", "Tệp đã gán (Tên gốc)", "Tên mới dự kiến", "Thao tác"
        ])
        q_hdr = self.queue_table.horizontalHeader()
        q_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        q_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        q_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        q_hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setColumnWidth(1, 220)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        right_layout.addWidget(self.queue_table)
        splitter.addWidget(right_widget)

        splitter.setSizes([380, 760])
        root_layout.addWidget(splitter)


        # ── Bottom Action Bar ──
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 8.5pt;")
        bottom_bar.addWidget(self.lbl_status)

        bottom_bar.addStretch()

        self.btn_cancel = QPushButton("Hủy bỏ")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(self.btn_cancel)

        self.btn_execute = QPushButton("✔  Thực hiện đổi tên theo thứ tự")
        self.btn_execute.setObjectName("btnPrimary")
        self.btn_execute.setStyleSheet(
            "QPushButton#btnPrimary { background-color: #0a84ff; color: white; "
            "font-weight: 600; padding: 6px 20px; border-radius: 5px; }"
            "QPushButton#btnPrimary:hover { background-color: #0071e3; }"
            "QPushButton#btnPrimary:disabled { background-color: #3a3a3c; color: #636366; }"
        )
        self.btn_execute.clicked.connect(self._execute)
        bottom_bar.addWidget(self.btn_execute)

        root_layout.addLayout(bottom_bar)

    # ─────────────────────────────────────────────
    # Data Population & Display
    # ─────────────────────────────────────────────

    def _populate_all(self):
        self._populate_pool()
        self._populate_queue_table()
        self._update_counts()

    def _populate_pool(self):
        """Populate the left side list with unassigned files."""
        self.pool_list.clear()
        assigned_paths = {info.path for info in self.slots if info is not None}

        for info in self.files:
            if info.path in assigned_paths:
                continue

            item = QListWidgetItem()
            item.setText(info.name)
            item.setData(Qt.ItemDataRole.UserRole, str(info.path))

            # Build subtitle with dimensions/date
            sub_parts = []
            if info.width and info.height:
                sub_parts.append(f"{info.width}×{info.height}")
            if info.created:
                sub_parts.append(info.created.strftime('%Y-%m-%d'))
            sub_text = " • ".join(sub_parts)
            if sub_text:
                item.setToolTip(f"{info.name}\n{sub_text}")

            self.pool_list.addItem(item)

    def _populate_queue_table(self):
        """Render the right side table of N slots."""
        self.queue_table.setRowCount(self.total_count)
        self._refresh_queue_display()

    def _get_seq_str(self, index_1based: int) -> str:
        idx_combo = self.combo_digits.currentIndex()
        if idx_combo == 0:
            return f"{index_1based:03d}"
        elif idx_combo == 1:
            return f"{index_1based:02d}"
        else:
            return str(index_1based)

    def _compute_slot_new_name(self, info: FileInfo, index_1based: int) -> str:
        """Formula: [Số thứ tự]_[Tên theo quy tắc cũ]."""
        seq_str = self._get_seq_str(index_1based)
        date_fmt = self.combo_date_fmt.currentText()
        old_rule_name = build_new_name(info, date_fmt=date_fmt)
        return f"{seq_str}_{old_rule_name}"

    def _refresh_queue_display(self):
        """Update all rows in the queue table."""
        self.queue_table.setUpdatesEnabled(False)
        for row in range(self.total_count):
            seq_num = row + 1
            seq_str = self._get_seq_str(seq_num)
            info = self.slots[row]

            # Col 0: Seq number badge
            seq_item = QTableWidgetItem(f"#{seq_str}")
            seq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            seq_item.setForeground(QColor("#0a84ff"))
            seq_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            self.queue_table.setItem(row, 0, seq_item)

            if info is not None:
                # Col 1: Original name
                orig_item = QTableWidgetItem(info.name)
                orig_item.setToolTip(str(info.path))
                self.queue_table.setItem(row, 1, orig_item)

                # Col 2: New planned name
                new_name = self._compute_slot_new_name(info, seq_num)
                new_item = QTableWidgetItem(new_name)
                new_item.setForeground(QColor("#30d158"))
                new_item.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
                self.queue_table.setItem(row, 2, new_item)

                # Col 3: Actions (Move Up, Move Down, Remove)
                action_widget = QWidget()
                act_layout = QHBoxLayout(action_widget)
                act_layout.setContentsMargins(2, 2, 2, 2)
                act_layout.setSpacing(4)

                btn_up = QPushButton("▲")
                btn_up.setFixedSize(22, 20)
                btn_up.setEnabled(row > 0)
                btn_up.clicked.connect(lambda ch, r=row: self._move_slot(r, -1))
                act_layout.addWidget(btn_up)

                btn_dn = QPushButton("▼")
                btn_dn.setFixedSize(22, 20)
                btn_dn.setEnabled(row < self.total_count - 1)
                btn_dn.clicked.connect(lambda ch, r=row: self._move_slot(r, 1))
                act_layout.addWidget(btn_dn)

                btn_rm = QPushButton("✖")
                btn_rm.setFixedSize(22, 20)
                btn_rm.setStyleSheet("color: #ff453a;")
                btn_rm.clicked.connect(lambda ch, r=row: self._clear_slot(r))
                act_layout.addWidget(btn_rm)

                self.queue_table.setCellWidget(row, 3, action_widget)
            else:
                # Empty slot
                orig_item = QTableWidgetItem("— Trống (Kéo thả tệp vào đây) —")
                orig_item.setForeground(QColor("#636366"))
                self.queue_table.setItem(row, 1, orig_item)

                new_item = QTableWidgetItem("—")
                new_item.setForeground(QColor("#48484a"))
                self.queue_table.setItem(row, 2, new_item)

                self.queue_table.setCellWidget(row, 3, None)

        self.queue_table.setUpdatesEnabled(True)
        self._update_counts()

    def _update_counts(self):
        assigned_count = sum(1 for s in self.slots if s is not None)
        unassigned_count = self.total_count - assigned_count

        self.lbl_pool_count.setText(f"📦 Kho tệp nguồn ({unassigned_count} tệp chưa xếp):")
        self.lbl_queue_count.setText(f"🔢 Hàng đợi thứ tự ({assigned_count}/{self.total_count} vị trí đã gán):")
        self.btn_execute.setEnabled(assigned_count > 0)

        if assigned_count == self.total_count:
            self.lbl_status.setText(f"✅ Đã xếp đủ {self.total_count}/{self.total_count} tệp! Sẵn sàng đổi tên.")
            self.lbl_status.setStyleSheet("color: #30d158; font-size: 8.5pt;")
        else:
            self.lbl_status.setText(f"Đã xếp {assigned_count}/{self.total_count} tệp vào hàng đợi.")
            self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 8.5pt;")

    # ─────────────────────────────────────────────
    # Slot Interactions (Drag-drop, Double-click, Move)
    # ─────────────────────────────────────────────

    def _on_file_dropped(self, row: int, path: Path):
        info = self.info_by_path.get(path)
        if not info:
            return

        # Check if this file was already in another slot
        existing_idx = None
        for i, s in enumerate(self.slots):
            if s and s.path == path:
                existing_idx = i
                break

        if existing_idx is not None and existing_idx != row:
            # Swap or move
            target_existing = self.slots[row]
            self.slots[row] = info
            self.slots[existing_idx] = target_existing
        else:
            self.slots[row] = info

        self._populate_pool()
        self._refresh_queue_display()

    def _on_pool_double_clicked(self, item: QListWidgetItem):
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        info = self.info_by_path.get(Path(path_str))
        if not info:
            return

        # Find first empty slot
        for i in range(self.total_count):
            if self.slots[i] is None:
                self.slots[i] = info
                self._populate_pool()
                self._refresh_queue_display()
                return

    def _move_slot(self, row: int, direction: int):
        target_row = row + direction
        if 0 <= target_row < self.total_count:
            self.slots[row], self.slots[target_row] = self.slots[target_row], self.slots[row]
            self._refresh_queue_display()

    def _clear_slot(self, row: int):
        self.slots[row] = None
        self._populate_pool()
        self._refresh_queue_display()

    def _fill_remaining_slots(self):
        """Fill all empty slots with remaining unassigned files."""
        unassigned = [
            f for f in self.files
            if f not in [s for s in self.slots if s is not None]
        ]
        u_idx = 0
        for i in range(self.total_count):
            if self.slots[i] is None and u_idx < len(unassigned):
                self.slots[i] = unassigned[u_idx]
                u_idx += 1

        self._populate_pool()
        self._refresh_queue_display()

    def _auto_sort(self, mode: str):
        """Auto-populate the entire queue sorted by chosen attribute."""
        sorted_files = list(self.files)
        if mode == "date_asc":
            sorted_files.sort(key=lambda f: f.created or f.path.stat().st_mtime)
        elif mode == "date_desc":
            sorted_files.sort(key=lambda f: f.created or f.path.stat().st_mtime, reverse=True)
        elif mode == "name":
            sorted_files.sort(key=lambda f: f.name.lower())

        for i in range(self.total_count):
            self.slots[i] = sorted_files[i] if i < len(sorted_files) else None

        self._populate_pool()
        self._refresh_queue_display()

    def _reset_queue(self):
        """Clear all slots and return all files to source pool."""
        self.slots = [None] * self.total_count
        self._populate_pool()
        self._refresh_queue_display()

    def _filter_pool(self, query: str):
        q = query.strip().lower()
        for i in range(self.pool_list.count()):
            item = self.pool_list.item(i)
            item.setHidden(bool(q and q not in item.text().lower()))

    # ─────────────────────────────────────────────
    # Execution
    # ─────────────────────────────────────────────

    def _execute(self):
        assigned_pairs = [
            (i + 1, info) for i, info in enumerate(self.slots) if info is not None
        ]
        if not assigned_pairs:
            QMessageBox.information(self, "Thông báo", "Chưa có tệp nào được xếp vào hàng đợi.")
            return

        if len(assigned_pairs) < self.total_count:
            reply = QMessageBox.question(
                self, "Hàng đợi chưa đầy",
                f"Bạn chỉ mới xếp {len(assigned_pairs)}/{self.total_count} tệp.\n"
                f"Chỉ đổi tên {len(assigned_pairs)} tệp này và giữ nguyên các tệp còn lại?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Build RenameOperations
        ops: list[RenameOperation] = []
        for seq_num, info in assigned_pairs:
            new_name = self._compute_slot_new_name(info, seq_num)
            dst_path = info.path.parent / new_name
            ops.append(RenameOperation(src=info.path, dst=dst_path, dry_run=False))

        self.btn_execute.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang đổi tên hàng đợi...", parent=self)
        log_path = Path("rename_log.jsonl")
        logger = RenameLogger(log_path, compute_checksums=False)
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

    def _on_rename_finished(self, ops: list):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn thành đổi tên!")

        self.btn_execute.setEnabled(True)
        log_path = Path("rename_log.jsonl")

        errors = [op for op in ops if op.error]
        if errors:
            err_msg = "\n".join(f"- {op.src.name}: {op.error}" for op in errors[:5])
            QMessageBox.warning(
                self, "Hoàn thành có lỗi",
                f"Đổi tên hoàn thành. {len(errors)}/{len(ops)} tệp lỗi:\n{err_msg}\n\nLog: {log_path}"
            )
        else:
            QMessageBox.information(
                self, "Thành công",
                f"Đã đổi tên thành công {len(ops)} tệp theo đúng thứ tự hàng đợi!\n"
                f"File log phục vụ khôi phục: {log_path}"
            )

        self.rename_completed.emit(ops)
        self.accept()

    def _on_rename_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng thao tác bởi người dùng.")

        self.btn_execute.setEnabled(True)
        executed_ops = [op for op in getattr(self._worker, "ops", []) if getattr(op, "executed", False)]
        if executed_ops:
            self.rename_completed.emit(executed_ops)
            QMessageBox.information(
                self, "Đã hủy",
                f"Đã dừng tiến trình đổi tên hàng đợi theo yêu cầu của bạn.\n"
                f"Đã đổi {len(executed_ops)}/{len(getattr(self._worker, 'ops', []))} tệp trước khi dừng."
            )
        else:
            QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình đổi tên hàng đợi.")

    def _on_rename_error(self, err: str):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_execute.setEnabled(True)
        QMessageBox.critical(self, "Lỗi khi đổi tên", f"Đã xảy ra lỗi: {err}")

    def closeEvent(self, event):
        if hasattr(self, "_worker") and self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)
        super().closeEvent(event)

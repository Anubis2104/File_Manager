"""
ui/dialogs/stats_dialog.py
Visual statistics and disk usage analyzer for scanned directories.
"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Optional
import threading

from PyQt6.QtCore  import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui   import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox,
    QHeaderView, QAbstractItemView, QGroupBox, QTabWidget,
    QWidget, QSplitter,
)

from ui.widgets.progress_dialog import TaskProgressDialog
from utils.file_utils import classify_extension


def format_size(bytes_val: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1048576:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1073741824:
        return f"{bytes_val / 1048576:.2f} MB"
    else:
        return f"{bytes_val / 1073741824:.2f} GB"


class StatsWorker(QObject):
    progress  = pyqtSignal(int, str)
    finished  = pyqtSignal(dict)
    cancelled = pyqtSignal()

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        stats = {
            "total_files": 0,
            "total_dirs": 0,
            "total_size": 0,
            "categories": defaultdict(lambda: {"count": 0, "size": 0}),
            "extensions": defaultdict(lambda: {"count": 0, "size": 0}),
            "largest_files": [],
        }

        all_files = []
        try:
            for p in self.root.rglob("*"):
                if p.is_dir():
                    stats["total_dirs"] += 1
                elif p.is_file():
                    stats["total_files"] += 1
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        sz = 0
                    stats["total_size"] += sz

                    cat = classify_extension(p.suffix)
                    stats["categories"][cat]["count"] += 1
                    stats["categories"][cat]["size"] += sz

                    ext = p.suffix.lower() or "(no ext)"
                    stats["extensions"][ext]["count"] += 1
                    stats["extensions"][ext]["size"] += sz

                    all_files.append((p, sz))
                    if len(all_files) % 100 == 0:
                        if self.is_cancelled:
                            self.cancelled.emit()
                            return
                        self.progress.emit(len(all_files), p.name)
        except Exception:
            pass

        if self.is_cancelled:
            self.cancelled.emit()
            return

        # Top 15 largest files
        all_files.sort(key=lambda x: x[1], reverse=True)
        stats["largest_files"] = all_files[:15]

        self.finished.emit(stats)


class StatsDialog(QDialog):
    """
    Folder Statistics & Space Analyzer Dialog.
    """

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.setWindowTitle(f"Thống kê thư mục: {root.name}")
        self.setMinimumSize(780, 540)
        self._thread = None
        self._worker = None
        self._build_ui()
        self._start_calc()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ── Header overview cards ──
        cards_layout = QHBoxLayout()

        self.card_files = self._create_card("Tổng số File", "Đang tính...")
        self.card_size  = self._create_card("Tổng dung lượng", "Đang tính...")
        self.card_media = self._create_card("Ảnh & Video", "Đang tính...")
        self.card_dirs  = self._create_card("Thư mục con", "Đang tính...")

        cards_layout.addWidget(self.card_files)
        cards_layout.addWidget(self.card_size)
        cards_layout.addWidget(self.card_media)
        cards_layout.addWidget(self.card_dirs)
        layout.addLayout(cards_layout)

        # ── Tabs ──
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Top Largest Files
        self.table_largest = QTableWidget()
        self.table_largest.setColumnCount(3)
        self.table_largest.setHorizontalHeaderLabels(["Tên File", "Dung lượng", "Đường dẫn"])
        hdr1 = self.table_largest.horizontalHeader()
        hdr1.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr1.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr1.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_largest.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_largest.verticalHeader().setVisible(False)
        self.tabs.addTab(self.table_largest, "🏆 Top File lớn nhất")

        # Tab 2: Extension breakdown
        self.table_ext = QTableWidget()
        self.table_ext.setColumnCount(3)
        self.table_ext.setHorizontalHeaderLabels(["Định dạng (Ext)", "Số lượng", "Tổng dung lượng"])
        hdr2 = self.table_ext.horizontalHeader()
        hdr2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_ext.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_ext.verticalHeader().setVisible(False)
        self.tabs.addTab(self.table_ext, "📁 Phân loại định dạng")

        self.lbl_status = QLabel("Đang quét phân tích cây thư mục...")
        self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _create_card(self, title: str, val: str) -> QGroupBox:
        box = QGroupBox(title)
        l = QVBoxLayout(box)
        lbl = QLabel(val)
        lbl.setObjectName("cardValue")
        lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #0a84ff; padding: 4px;")
        l.addWidget(lbl)
        return box

    def _start_calc(self):
        self._progress_dlg = TaskProgressDialog("Đang quét thống kê thư mục...", parent=self)
        self._progress_dlg.set_indeterminate(f"🔍 Đang quét và phân tích thống kê: {self.root.name}")
        self._progress_dlg.lbl_icon.setText("📊")

        self._worker = StatsWorker(self.root)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(lambda n, name: (
            self.lbl_status.setText(f"Đã duyệt: {n} file ({name})"),
            self._progress_dlg.lbl_status.setText(f"Đã duyệt {n} file: {name}"),
        ))
        self._worker.finished.connect(self._on_finished)
        self._worker.cancelled.connect(self._on_cancelled)
        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_finished(self, stats: dict):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)
        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Phân tích hoàn tất!")
        self.lbl_status.setText("Phân tích hoàn tất.")

        # Update cards
        self.card_files.findChild(QLabel, "cardValue").setText(f"{stats['total_files']:,}")
        self.card_size.findChild(QLabel, "cardValue").setText(format_size(stats["total_size"]))
        media_cnt = stats["categories"]["image"]["count"] + stats["categories"]["video"]["count"]
        self.card_media.findChild(QLabel, "cardValue").setText(f"{media_cnt:,}")
        self.card_dirs.findChild(QLabel, "cardValue").setText(f"{stats['total_dirs']:,}")

        # Top largest table
        largest = stats["largest_files"]
        self.table_largest.setRowCount(len(largest))
        for row, (path, sz) in enumerate(largest):
            self.table_largest.setItem(row, 0, QTableWidgetItem(path.name))
            self.table_largest.setItem(row, 1, QTableWidgetItem(format_size(sz)))
            self.table_largest.setItem(row, 2, QTableWidgetItem(str(path.parent)))

        # Extensions table
        exts = sorted(stats["extensions"].items(), key=lambda x: x[1]["size"], reverse=True)
        self.table_ext.setRowCount(len(exts))
        for row, (ext, data) in enumerate(exts):
            self.table_ext.setItem(row, 0, QTableWidgetItem(ext))
            self.table_ext.setItem(row, 1, QTableWidgetItem(f"{data['count']:,}"))
            self.table_ext.setItem(row, 2, QTableWidgetItem(format_size(data["size"])))

    def _on_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)
        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng thống kê.")
        self.lbl_status.setText("Đã dừng tính toán.")

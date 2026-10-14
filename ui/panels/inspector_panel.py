"""
ui/panels/inspector_panel.py
Security & Byte Inspection Panel.
Professional, minimalist UI for 5-layer binary validation,
trailing overlay auto-trimming, and Windows AMSI scanning.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QComboBox, QFrame, QFileDialog, QMessageBox, QSplitter,
    QSizePolicy,
)

from core.inspector import format_bytes, repair_jpeg_header
from core.workers import InspectorWorker, TrimOverlayWorker
from ui.widgets.progress_dialog import TaskProgressDialog


class StatCard(QFrame):
    """Clean stat card widget with title and prominent metric value."""

    def __init__(self, title: str, initial_val: str = "0", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("statCardTitle")
        layout.addWidget(self.lbl_title)

        self.lbl_value = QLabel(initial_val)
        self.lbl_value.setObjectName("statCardValue")
        layout.addWidget(self.lbl_value)

    def set_value(self, val: str | int):
        self.lbl_value.setText(str(val))


class InspectorPanel(QWidget):
    """
    Byte Inspection & Security Panel.
    Enables deep multi-layered file inspection, overlay trimming, and quarantine management.
    """

    scan_started = pyqtSignal(str)   # path
    scan_finished = pyqtSignal(int)  # count

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inspected_items: list[dict] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[InspectorWorker] = None
        self._current_target_dir: Optional[Path] = None

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # ── 1. Header & Controls Bar ──
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(10)

        self.btn_select_dir = QPushButton("Chọn thư mục")
        self.btn_select_dir.setObjectName("primaryButton")
        self.btn_select_dir.clicked.connect(self._select_dir)
        ctrl_bar.addWidget(self.btn_select_dir)

        self.btn_scan = QPushButton("Quét kiểm định")
        self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._start_scan)
        ctrl_bar.addWidget(self.btn_scan)

        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        ctrl_bar.addWidget(self.btn_stop)

        self.chk_recursive = QCheckBox("Đệ quy thư mục con")
        self.chk_recursive.setChecked(True)
        ctrl_bar.addWidget(self.chk_recursive)

        self.chk_amsi = QCheckBox("Quét mã độc AMSI (Windows Defender)")
        self.chk_amsi.setChecked(True)
        ctrl_bar.addWidget(self.chk_amsi)

        ctrl_bar.addStretch()

        self.lbl_filter = QLabel("Lọc hiển thị:")
        ctrl_bar.addWidget(self.lbl_filter)

        self.cb_filter = QComboBox()
        self.cb_filter.addItems([
            "Tất cả tệp",
            "Chỉ tệp có Trailing Overlay",
            "Chỉ tệp lỗi / hỏng",
            "Chỉ tệp bị cách ly / nguy hiểm",
        ])
        self.cb_filter.currentIndexChanged.connect(self._apply_filter)
        ctrl_bar.addWidget(self.cb_filter)

        root_layout.addLayout(ctrl_bar)

        # ── 2. Stat Metric Cards ──
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)

        self.card_total = StatCard("Tổng số tệp quét")
        self.card_clean = StatCard("Tệp hợp lệ")
        self.card_overlay = StatCard("Tệp dôi dư Overlay")
        self.card_corrupted = StatCard("Tệp hỏng")
        self.card_quarantined = StatCard("Tệp đã cách ly")

        stats_layout.addWidget(self.card_total)
        stats_layout.addWidget(self.card_clean)
        stats_layout.addWidget(self.card_overlay)
        stats_layout.addWidget(self.card_corrupted)
        stats_layout.addWidget(self.card_quarantined)

        root_layout.addLayout(stats_layout)

        # ── 3. Table of Results ──
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Tên tệp", "Trạng thái", "Phân loại", "Chi tiết", "Dung lượng dôi dư", "Đường dẫn",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(5, 260)

        root_layout.addWidget(self.table)

        # ── 4. Bottom Action Bar ──
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.btn_trim_selected = QPushButton("Gọt Overlay các mục chọn")
        self.btn_trim_selected.clicked.connect(self._trim_selected)
        action_bar.addWidget(self.btn_trim_selected)

        self.btn_trim_all = QPushButton("Gọt sạch tất cả Overlay")
        self.btn_trim_all.setObjectName("accentButton")
        self.btn_trim_all.clicked.connect(self._trim_all)
        action_bar.addWidget(self.btn_trim_all)

        self.btn_repair_jpg = QPushButton("Sửa Header JPEG")
        self.btn_repair_jpg.clicked.connect(self._repair_selected_jpeg)
        action_bar.addWidget(self.btn_repair_jpg)

        action_bar.addStretch()

        self.btn_open_quarantine = QPushButton("Mở thư mục Cách ly")
        self.btn_open_quarantine.clicked.connect(self._open_quarantine_folder)
        action_bar.addWidget(self.btn_open_quarantine)

        root_layout.addLayout(action_bar)

    def set_directory(self, target_dir: Path):
        """Set active target directory for scanning."""
        self._current_target_dir = Path(target_dir)
        self.btn_scan.setEnabled(True)

    def _select_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Chọn thư mục cần kiểm định")
        if chosen:
            self.set_directory(Path(chosen))
            self._start_scan()

    def _start_scan(self):
        if not self._current_target_dir or not self._current_target_dir.is_dir():
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn thư mục hợp lệ.")
            return

        self._inspected_items.clear()
        self.table.setRowCount(0)
        self._update_stat_cards()

        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.scan_started.emit(str(self._current_target_dir))

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang kiểm định tệp...", parent=self.window())
        self._progress_dlg.set_indeterminate("🔍 Đang quét và kiểm tra tính toàn vẹn nhị phân...")
        self._progress_dlg.lbl_icon.setText("🛡️")

        self._worker_thread = QThread(self)
        self._worker = InspectorWorker(
            root=self._current_target_dir,
            recursive=self.chk_recursive.isChecked(),
            run_amsi=self.chk_amsi.isChecked(),
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._stop_scan, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.file_inspected.connect(self._on_file_inspected)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.cancelled.connect(self._on_scan_cancelled)
        self._worker.error.connect(self._on_scan_error)

        self._progress_dlg.show_centered()
        self._worker_thread.start()

    def _stop_scan(self):
        if self._worker:
            self._worker.cancel()
        self.btn_stop.setEnabled(False)

    def _on_file_inspected(self, item: dict):
        self._inspected_items.append(item)
        self._add_row(item)
        self._update_stat_cards()

    def _on_scan_finished(self, results: list):
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task(f"Đã kiểm định xong {len(results)} tệp!")

        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.scan_finished.emit(len(results))

    def _on_scan_cancelled(self):
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng kiểm định.")

        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình kiểm định theo yêu cầu.")

    def _on_scan_error(self, err_msg: str):
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        QMessageBox.critical(self, "Lỗi kiểm định", err_msg)

    def _add_row(self, item: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        item_name = QTableWidgetItem(item.get("file", ""))
        item_status = QTableWidgetItem(item.get("status", "UNKNOWN"))
        item_reason = QTableWidgetItem(item.get("reason", ""))
        item_details = QTableWidgetItem(item.get("details", ""))

        bytes_val = item.get("bytes_stripped", 0)
        item_bytes = QTableWidgetItem(format_bytes(bytes_val) if bytes_val > 0 else "—")
        item_path = QTableWidgetItem(item.get("path", ""))

        status = item.get("status", "")
        if status == "CLEAN":
            item_status.setForeground(QBrush(QColor("#10b981")))  # emerald
        elif status == "OVERLAY":
            item_status.setForeground(QBrush(QColor("#f59e0b")))  # amber
        elif status in ("CORRUPTED", "ERROR"):
            item_status.setForeground(QBrush(QColor("#f43f5e")))  # rose
        elif status in ("THREAT", "QUARANTINED"):
            item_status.setForeground(QBrush(QColor("#ec4899")))  # pink/purple

        self.table.setItem(row, 0, item_name)
        self.table.setItem(row, 1, item_status)
        self.table.setItem(row, 2, item_reason)
        self.table.setItem(row, 3, item_details)
        self.table.setItem(row, 4, item_bytes)
        self.table.setItem(row, 5, item_path)

    def _update_stat_cards(self):
        total = len(self._inspected_items)
        clean = sum(1 for i in self._inspected_items if i.get("status") == "CLEAN")
        overlay = sum(1 for i in self._inspected_items if i.get("status") == "OVERLAY")
        corrupted = sum(1 for i in self._inspected_items if i.get("status") in ("CORRUPTED", "ERROR"))
        quarantined = sum(1 for i in self._inspected_items if i.get("status") in ("THREAT", "QUARANTINED"))

        self.card_total.set_value(total)
        self.card_clean.set_value(clean)
        self.card_overlay.set_value(overlay)
        self.card_corrupted.set_value(corrupted)
        self.card_quarantined.set_value(quarantined)

    def _apply_filter(self):
        choice = self.cb_filter.currentIndex()
        for r in range(self.table.rowCount()):
            status_item = self.table.item(r, 1)
            status_text = status_item.text() if status_item else ""

            if choice == 0:
                self.table.setRowHidden(r, False)
            elif choice == 1:
                self.table.setRowHidden(r, status_text != "OVERLAY")
            elif choice == 2:
                self.table.setRowHidden(r, status_text not in ("CORRUPTED", "ERROR"))
            elif choice == 3:
                self.table.setRowHidden(r, status_text not in ("THREAT", "QUARANTINED"))

    def _trim_selected(self):
        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        if not selected_rows:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn ít nhất một tệp trong bảng.")
            return

        items_to_trim = []
        for r in selected_rows:
            fpath = self.table.item(r, 5).text()
            item = next((i for i in self._inspected_items if i.get("path") == fpath), None)
            if item and item.get("can_trim"):
                items_to_trim.append(item)

        if not items_to_trim:
            QMessageBox.information(self, "Thông báo", "Các mục được chọn không có Trailing Overlay để gọt.")
            return

        self._execute_trim(items_to_trim)

    def _trim_all(self):
        items_to_trim = [i for i in self._inspected_items if i.get("can_trim")]
        if not items_to_trim:
            QMessageBox.information(self, "Thông báo", "Không có tệp nào chứa Trailing Overlay cần gọt.")
            return

        reply = QMessageBox.question(
            self, "Xác nhận",
            f"Bạn có chắc chắn muốn gọt bỏ dữ liệu thừa của {len(items_to_trim)} tệp tin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._execute_trim(items_to_trim)

    def _execute_trim(self, items: list[dict]):
        from core.inspector import trim_file_overlay

        success_count = 0
        total_cut = 0
        failures: list[str] = []
        for item in items:
            fpath = item.get("path")
            valid_end = item.get("valid_end_pos")
            ok, cut_len, msg = trim_file_overlay(fpath, valid_end, backup_dir=self._quarantine_dir())
            if ok:
                success_count += 1
                total_cut += cut_len
                item["status"] = "CLEAN"
                item["reason"] = "Đã gọt sạch Overlay"
                item["details"] = f"Đã gọt bỏ {format_bytes(cut_len)}"
                item["can_trim"] = False
            else:
                failures.append(f"{Path(fpath).name}: {msg}")

        # Reload table rows
        self.table.setRowCount(0)
        for it in self._inspected_items:
            self._add_row(it)
        self._update_stat_cards()
        self._apply_filter()

        QMessageBox.information(
            self, "Hoàn tất",
            f"Đã gọt bỏ thành công {success_count} tệp tin.\nTổng dung lượng giải phóng: {format_bytes(total_cut)}"
            f"\nPhần dữ liệu đã gọt được sao lưu tại: {self._quarantine_dir()}",
        )
        self._show_failures("Gọt overlay", failures)

    def _repair_selected_jpeg(self):
        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        if not selected_rows:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn tệp JPEG cần sửa header.")
            return

        repaired = 0
        failures: list[str] = []
        for r in selected_rows:
            fpath = self.table.item(r, 5).text()
            ok, msg = repair_jpeg_header(fpath, backup_dir=self._quarantine_dir())
            if ok:
                repaired += 1
            else:
                failures.append(f"{Path(fpath).name}: {msg}")

        QMessageBox.information(
            self, "Hoàn tất",
            f"Đã kiểm tra và sửa cấu trúc Header cho {repaired} tệp tin.",
        )
        self._show_failures("Sửa header JPEG", failures)

    def _show_failures(self, action: str, failures: list[str]):
        if not failures:
            return
        shown = "\n".join(f"• {f}" for f in failures[:10])
        more = f"\n… và {len(failures) - 10} tệp khác" if len(failures) > 10 else ""
        QMessageBox.warning(self, f"{action}: {len(failures)} tệp thất bại", shown + more)

    def _quarantine_dir(self) -> Path:
        return self._current_target_dir / "_Quarantine" if self._current_target_dir else Path.cwd() / "_Quarantine"

    def _open_quarantine_folder(self):
        q_dir = self._quarantine_dir()
        q_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(q_dir))
        else:
            import subprocess
            subprocess.run(["xdg-open", str(q_dir)])

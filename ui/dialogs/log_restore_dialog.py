"""
ui/dialogs/log_restore_dialog.py
Dialog for viewing rename log and restoring original filenames.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QThread
from PyQt6.QtGui   import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QHeaderView, QAbstractItemView,
    QCheckBox, QGroupBox,
)

from core.logger  import RenameLogger, LogEntry
from ui.widgets.progress_dialog import TaskProgressDialog
from ui.theme import qcolor, style, tok


class LogRestoreDialog(QDialog):
    """
    Load a JSONL rename log file, display entries in a table,
    and allow selective or full restore.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Khôi phục từ Log")
        self.setMinimumSize(900, 520)
        self._entries: list[LogEntry] = []
        self._log_path: Optional[Path] = None
        self._thread: Optional[QThread] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── File picker ──
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("File log (.jsonl):"))

        self.log_path_edit = QLineEdit()
        self.log_path_edit.setPlaceholderText("Chọn hoặc nhập đường dẫn file log...")
        file_row.addWidget(self.log_path_edit)

        btn_browse = QPushButton("📁  Chọn file")
        btn_browse.clicked.connect(self._browse_log)
        file_row.addWidget(btn_browse)

        btn_load = QPushButton("📖  Tải log")
        btn_load.setObjectName("btnPrimary")
        btn_load.clicked.connect(self._load_log)
        file_row.addWidget(btn_load)

        layout.addLayout(file_row)

        # ── Options ──
        opt_group = QGroupBox("Tùy chọn khôi phục")
        opt_layout = QHBoxLayout(opt_group)
        self.chk_verify = QCheckBox("Kiểm tra checksum MD5 trước khi khôi phục")
        self.chk_verify.setChecked(True)
        opt_layout.addWidget(self.chk_verify)
        opt_layout.addStretch()
        layout.addWidget(opt_group)

        # ── Table ──
        info_lbl = QLabel("Danh sách thao tác rename (mới nhất trước):")
        style(info_lbl, "color: @text_secondary; font-size: 11px; font-weight: 600;")
        layout.addWidget(info_lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Thời gian", "Loại", "Tên gốc", "Tên mới", "Trạng thái"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)


        self.lbl_status = QLabel("")
        style(self.lbl_status, "color: @text_secondary; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_close = QPushButton("Đóng")
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_close)

        self.btn_restore_all = QPushButton("⟲  Khôi phục tất cả")
        self.btn_restore_all.setObjectName("btnPrimary")
        self.btn_restore_all.setEnabled(False)
        self.btn_restore_all.clicked.connect(self._restore_all)
        btn_row.addWidget(self.btn_restore_all)

        layout.addLayout(btn_row)

    # ─────────────────────────────────────────────
    # Log operations
    # ─────────────────────────────────────────────

    def _browse_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file log", "",
            "JSON Lines (*.jsonl);;All Files (*)"
        )
        if path:
            self.log_path_edit.setText(path)
            self._load_log()

    def _load_log(self):
        path_str = self.log_path_edit.text().strip()
        if not path_str:
            return
        log_path = Path(path_str)
        if not log_path.exists():
            QMessageBox.warning(self, "Lỗi", f"File không tồn tại:\n{log_path}")
            return

        self._log_path = log_path
        logger = RenameLogger(log_path)
        self._entries = logger.read_entries()

        self._populate_table()
        self.btn_restore_all.setEnabled(
            any(e.operation == "rename" for e in self._entries)
        )
        self.lbl_status.setText(
            f"Tải {len(self._entries)} bản ghi từ log."
        )

    def _populate_table(self):
        entries = list(reversed(self._entries))  # newest first
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            ts_str = entry.timestamp.strftime("%d/%m/%y %H:%M")
            op_color = {
                "rename": tok("accent"),
                "restore": tok("success"),
                "dry_rename": tok("text_tertiary"),
                "strip_metadata": tok("warning"),
            }.get(entry.operation, tok("text_secondary"))

            items = [
                QTableWidgetItem(ts_str),
                QTableWidgetItem(entry.operation),
                QTableWidgetItem(entry.src_name),
                QTableWidgetItem(entry.dst_name),
                QTableWidgetItem("✔" if not entry.error else f"✖ {entry.error[:30]}"),
            ]
            items[1].setForeground(QColor(op_color))
            if entry.error:
                items[4].setForeground(qcolor("danger"))

            for col, item in enumerate(items):
                self.table.setItem(row, col, item)

    def _restore_all(self):
        if not self._log_path:
            return
        reply = QMessageBox.question(
            self, "Xác nhận khôi phục",
            "Khôi phục TẤT CẢ file rename trong log về tên gốc?\n\n"
            "Thao tác sẽ đổi tên ngược lại (tên mới → tên gốc).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_restore_all.setEnabled(False)

        dlg = TaskProgressDialog("Đang khôi phục từ log...", parent=self)
        dlg.set_task("Khôi phục tệp theo nhật ký WAL...", total=len(self._entries), icon="⏮️")

        cancelled = False
        def on_cancel():
            nonlocal cancelled
            cancelled = True

        dlg.cancelled.connect(on_cancel)
        dlg.show_centered()

        logger = RenameLogger(self._log_path)
        results = logger.restore_from_log(
            verify_checksum=self.chk_verify.isChecked(),
            on_progress=lambda cur, tot: dlg.update_progress(cur, tot),
            cancel_check=lambda: cancelled,
        )

        if cancelled:
            dlg.cancel_task("Đã dừng khôi phục.")
            QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình khôi phục theo yêu cầu.")
        else:
            dlg.finish_task("Đã khôi phục xong!")

        ok = sum(1 for r in results if r["success"])
        fail = len(results) - ok
        self.lbl_status.setText(
            f"Khôi phục: ✅ {ok} thành công  {'❌ ' + str(fail) + ' lỗi' if fail else ''}"
        )
        self.btn_restore_all.setEnabled(True)
        self._load_log()   # Refresh table

        if fail:
            # Group by reason (text before the first ':' drops per-file paths)
            reasons = Counter(r["error"].split(":", 1)[0] or "Unknown error"
                              for r in results if not r["success"])
            lines = "\n".join(f"• {n} tệp: {reason}" for reason, n in reasons.most_common(6))
            QMessageBox.warning(
                self, "Có tệp không khôi phục được",
                f"Đã khôi phục {ok} tệp, {fail} tệp thất bại.\n\nNguyên nhân:\n{lines}",
            )

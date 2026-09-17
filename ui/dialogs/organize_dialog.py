"""
ui/dialogs/organize_dialog.py
Dialog for organizing files into subfolders by date or category with dry-run preview.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QThread, pyqtSignal
from PyQt6.QtGui   import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QHeaderView, QAbstractItemView, QGroupBox,
    QLineEdit, QFileDialog, QCheckBox,
)

from core.organizer import FileOrganizer
from core.workers   import RenameWorker
from core.logger    import RenameLogger
from utils.file_utils import RenameOperation
from ui.widgets.progress_dialog import TaskProgressDialog


class OrganizeDialog(QDialog):
    """
    Auto-organize files into date-based or type-based subfolder structures.
    """
    organize_completed = pyqtSignal(list)

    def __init__(self, files: list[Path], root_dir: Path, parent=None):
        super().__init__(parent)
        self.files = files
        self.root_dir = root_dir
        self.ops: list[RenameOperation] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[RenameWorker] = None

        self.setWindowTitle("Tự động gom nhóm & Sắp xếp thư mục")
        self.setMinimumSize(860, 560)
        self._build_ui()
        self._refresh_preview()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ── Settings group ──
        g_cfg = QGroupBox("Quy tắc gom nhóm")
        gc_layout = QVBoxLayout(g_cfg)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Cấu trúc thư mục mới:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("📅 Theo Năm / Tháng (YYYY / MM)", "date_year_month")
        self.combo_mode.addItem("📅 Theo Năm / Tháng / Ngày (YYYY / MM / DD)", "date_year_month_day")
        self.combo_mode.addItem("📁 Theo Loại tập tin (Images / Videos / Others)", "media_type")
        self.combo_mode.addItem("🏷️ Theo Định dạng (JPG / PNG / MP4...)", "extension")
        self.combo_mode.currentIndexChanged.connect(self._refresh_preview)
        row1.addWidget(self.combo_mode)
        row1.addStretch()
        gc_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Thư mục gốc đích:"))
        self.edit_target = QLineEdit(str(self.root_dir))
        self.edit_target.textChanged.connect(self._refresh_preview)
        row2.addWidget(self.edit_target)
        btn_browse = QPushButton("📁")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_target)
        row2.addWidget(btn_browse)
        gc_layout.addLayout(row2)

        layout.addWidget(g_cfg)

        # ── Preview Table ──
        self.lbl_summary = QLabel(f"Preview sắp xếp ({len(self.files)} file):")
        self.lbl_summary.setStyleSheet("color: #8e8e93; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.lbl_summary)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["File nguồn", "Thư mục đích mới", "Tên đích"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)


        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("🔄  Làm mới preview")
        btn_refresh.clicked.connect(self._refresh_preview)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()

        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_execute = QPushButton("✔  Thực hiện sắp xếp")
        self.btn_execute.setObjectName("btnPrimary")
        self.btn_execute.clicked.connect(self._execute)
        btn_row.addWidget(self.btn_execute)

        layout.addLayout(btn_row)

    def _browse_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục gốc đích", str(self.root_dir))
        if folder:
            self.edit_target.setText(folder)

    def _refresh_preview(self):
        mode = self.combo_mode.currentData()
        target_str = self.edit_target.text().strip()
        target_root = Path(target_str) if target_str else self.root_dir

        organizer = FileOrganizer(mode=mode, dry_run=True)
        self.ops = organizer.plan(self.files, target_root=target_root)

        self.table.setRowCount(len(self.ops))
        for row, op in enumerate(self.ops):
            self.table.setItem(row, 0, QTableWidgetItem(op.src.name))
            try:
                rel_parent = str(op.dst.parent.relative_to(target_root))
            except Exception:
                rel_parent = str(op.dst.parent)
            self.table.setItem(row, 1, QTableWidgetItem(rel_parent))
            self.table.setItem(row, 2, QTableWidgetItem(op.dst.name))

        self.lbl_summary.setText(f"Preview sắp xếp ({len(self.ops)} file):")
        self.lbl_status.setText(f"Sẽ di chuyển {len(self.ops)} file vào các thư mục tương ứng.")

    def _execute(self):
        if not self.ops:
            return

        reply = QMessageBox.question(
            self, "Xác nhận sắp xếp",
            f"Bạn có chắc muốn di chuyển {len(self.ops)} file vào cấu trúc thư mục mới?\n"
            f"(Thao tác có ghi nhận log và có thể khôi phục lại).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for op in self.ops:
            op.dry_run = False

        self.btn_execute.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang di chuyển sắp xếp tệp...", parent=self)
        self._progress_dlg.set_task("Đang di chuyển sắp xếp tệp...", total=len(self.ops), icon="📁")

        log_path = Path("organize_log.jsonl")
        logger = RenameLogger(log_path)
        self._worker = RenameWorker(ops=self.ops, logger=logger)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.progress.connect(
            lambda cur, tot, name: self.lbl_status.setText(f"Đang di chuyển ({cur}/{tot}): {name}")
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.error.connect(self._on_error)

        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_finished(self, ops: list):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn tất sắp xếp!")

        log_path = Path("organize_log.jsonl")

        ok_count = sum(1 for op in ops if not op.error)
        fail_count = len(ops) - ok_count
        QMessageBox.information(
            self, "Hoàn tất sắp xếp",
            f"Đã di chuyển thành công {ok_count}/{len(ops)} file.\n"
            f"File log đã lưu tại: {log_path.resolve()}"
        )
        self.organize_completed.emit(ops)
        self.accept()

    def _on_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng sắp xếp.")

        self.btn_execute.setEnabled(True)
        self.lbl_status.setText("⚠️ Thao tác sắp xếp đã bị hủy.")

        executed_ops = [op for op in getattr(self._worker, "ops", []) if getattr(op, "executed", False)]
        if executed_ops:
            self.organize_completed.emit(executed_ops)
            QMessageBox.information(
                self, "Đã hủy",
                f"Đã dừng tiến trình sắp xếp theo yêu cầu của bạn.\n"
                f"Đã sắp xếp {len(executed_ops)}/{len(getattr(self._worker, 'ops', []))} file trước khi dừng."
            )
        else:
            QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình sắp xếp theo yêu cầu của bạn.")

    def _on_error(self, err_msg: str):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_execute.setEnabled(True)
        QMessageBox.critical(self, "Lỗi", err_msg)

    def closeEvent(self, event):
        if hasattr(self, "_worker") and self._worker:
            self._worker.cancel()
        if hasattr(self, "_thread") and self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)
        super().closeEvent(event)

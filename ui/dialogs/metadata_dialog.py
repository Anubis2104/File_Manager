"""
ui/dialogs/metadata_dialog.py
Comprehensive Metadata management dialog.
Features:
- View raw metadata / EXIF tags of selected files
- Strip metadata with automated Safe Date Preservation
- Supports selected files, entire directory (recursive/shallow), or custom files
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QThread, pyqtSignal
from PyQt6.QtGui   import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox,
    QHeaderView, QAbstractItemView, QCheckBox, QGroupBox,
    QRadioButton, QButtonGroup, QFileDialog, QTextEdit,
    QSplitter, QWidget,
)

from core.metadata import MetadataEngine
from core.workers  import MetadataStripWorker
from utils.file_utils import classify_extension, IMAGE_EXTS, VIDEO_EXTS
from ui.widgets.progress_dialog import TaskProgressDialog
from ui.theme import qcolor, style


class MetadataViewerDialog(QDialog):
    """Sub-dialog to inspect all metadata tags of a single file."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(f"Metadata: {path.name}")
        self.setMinimumSize(600, 480)
        self._build_ui()
        self._load_tags()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.lbl_path = QLabel(f"<b>File:</b> {self.path}")
        style(self.lbl_path, "color: @accent; font-size: 11px;")
        layout.addWidget(self.lbl_path)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Thẻ (Tag)", "Giá trị (Value)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

    def _load_tags(self):
        engine = MetadataEngine()
        data = engine.read_all(self.path)
        if not data:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("Thông báo"))
            self.table.setItem(0, 1, QTableWidgetItem("Không tìm thấy metadata hoặc file không chứa thẻ EXIF."))
            return

        self.table.setRowCount(len(data))
        for row, (k, v) in enumerate(sorted(data.items())):
            k_item = QTableWidgetItem(str(k))
            v_item = QTableWidgetItem(str(v))
            if "date" in k.lower() or "time" in k.lower():
                k_item.setForeground(qcolor("success"))
                v_item.setForeground(qcolor("success"))
            self.table.setItem(row, 0, k_item)
            self.table.setItem(row, 1, v_item)


class MetadataDialog(QDialog):
    """
    Metadata Strip Dialog:
    - Choose scope: selected files, current directory, or custom files
    - Safe-wipe date preservation
    - Live progress and result table
    """
    metadata_stripped = pyqtSignal(list)

    def __init__(
        self,
        current_dir: Optional[Path] = None,
        selected_files: Optional[list[Path]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.current_dir = current_dir
        self.selected_files = selected_files or []
        self.target_files: list[Path] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[MetadataStripWorker] = None

        self.setWindowTitle("Quản lý & Xóa Metadata")
        self.setMinimumSize(880, 560)
        self._build_ui()
        self._init_targets()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Scope group ──
        scope_group = QGroupBox("Phạm vi xóa Metadata")
        scope_layout = QVBoxLayout(scope_group)

        self.radio_selected = QRadioButton("Các file đang chọn")
        self.radio_current_dir = QRadioButton("Toàn bộ thư mục hiện tại")
        self.radio_custom = QRadioButton("Tự chọn file / thư mục...")

        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.radio_selected, 0)
        self.btn_group.addButton(self.radio_current_dir, 1)
        self.btn_group.addButton(self.radio_custom, 2)

        radio_row = QHBoxLayout()
        radio_row.addWidget(self.radio_selected)
        radio_row.addWidget(self.radio_current_dir)
        radio_row.addWidget(self.radio_custom)
        radio_row.addStretch()

        self.btn_add_files = QPushButton("➕ Thêm file")
        self.btn_add_files.setFixedWidth(100)
        self.btn_add_files.clicked.connect(self._add_custom_files)
        self.btn_add_files.setVisible(False)
        radio_row.addWidget(self.btn_add_files)

        scope_layout.addLayout(radio_row)

        self.chk_recursive = QCheckBox("Đệ quy duyệt tất cả thư mục con")
        self.chk_recursive.setChecked(True)
        scope_layout.addWidget(self.chk_recursive)

        layout.addWidget(scope_group)

        # ── Options ──
        opt_group = QGroupBox("Tùy chọn bảo toàn")
        opt_layout = QHBoxLayout(opt_group)

        self.chk_preserve_date = QCheckBox("🛡️ Tự động bảo toàn ngày tháng tạo gốc (Safe Date Store)")
        self.chk_preserve_date.setChecked(True)
        self.chk_preserve_date.setToolTip(
            "Trích xuất ngày tạo trước khi xóa, xóa sạch metadata nhạy cảm,\n"
            "sau đó ghi lại ngày tạo vào EXIF DateTimeOriginal để ngày không bao giờ bị mất."
        )
        opt_layout.addWidget(self.chk_preserve_date)
        opt_layout.addStretch()

        btn_view_meta = QPushButton("🔍 Xem Metadata file đang chọn")
        btn_view_meta.clicked.connect(self._view_selected_metadata)
        opt_layout.addWidget(btn_view_meta)

        layout.addWidget(opt_group)

        # ── Table ──
        self.lbl_summary = QLabel("Danh sách file sẽ xử lý:")
        style(self.lbl_summary, "color: @text_secondary; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.lbl_summary)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Tên File", "Thư mục", "Ngày tạo", "Trạng thái"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 170)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._view_selected_metadata)
        layout.addWidget(self.table)

        self.lbl_status = QLabel("")
        style(self.lbl_status, "color: @text_secondary; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Đóng")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_execute = QPushButton("🔒  Bắt đầu xóa Metadata")
        self.btn_execute.setObjectName("btnPrimary")
        self.btn_execute.clicked.connect(self._start_strip)
        btn_row.addWidget(self.btn_execute)

        layout.addLayout(btn_row)

        # Signal connections
        self.radio_selected.toggled.connect(self._on_scope_changed)
        self.radio_current_dir.toggled.connect(self._on_scope_changed)
        self.radio_custom.toggled.connect(self._on_scope_changed)
        self.chk_recursive.toggled.connect(self._refresh_targets)

    def _init_targets(self):
        if self.selected_files:
            self.radio_selected.setChecked(True)
        elif self.current_dir:
            self.radio_current_dir.setChecked(True)
        else:
            self.radio_custom.setChecked(True)
        self._refresh_targets()

    def _on_scope_changed(self):
        is_custom = self.radio_custom.isChecked()
        self.btn_add_files.setVisible(is_custom)
        self._refresh_targets()

    def _add_custom_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn file ảnh/video", "",
            "Media files (*.jpg *.jpeg *.png *.webp *.tiff *.mp4 *.mov *.avi);;All Files (*)"
        )
        for p in paths:
            path = Path(p)
            if path not in self.target_files:
                self.target_files.append(path)
        self._populate_table()

    def _refresh_targets(self):
        self.target_files = []
        if self.radio_selected.isChecked():
            # Filter selected files or subfolders for image/video
            for p in self.selected_files:
                if p.is_file() and classify_extension(p.suffix) in ("image", "video"):
                    self.target_files.append(p)
                elif p.is_dir():
                    walker = p.rglob("*") if self.chk_recursive.isChecked() else p.iterdir()
                    try:
                        for sub_p in walker:
                            if sub_p.is_file() and classify_extension(sub_p.suffix) in ("image", "video"):
                                self.target_files.append(sub_p)
                    except Exception:
                        pass
        elif self.radio_current_dir.isChecked() and self.current_dir:
            walker = self.current_dir.rglob("*") if self.chk_recursive.isChecked() else self.current_dir.iterdir()
            try:
                for p in walker:
                    if p.is_file() and classify_extension(p.suffix) in ("image", "video"):
                        self.target_files.append(p)
            except Exception:
                pass
        self._populate_table()

    def _populate_table(self):
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.target_files))
            self.lbl_summary.setText(f"Danh sách file ({len(self.target_files)} file ảnh/video):")
            for row, path in enumerate(self.target_files):
                self.table.setItem(row, 0, QTableWidgetItem(path.name))
                self.table.setItem(row, 1, QTableWidgetItem(path.parent.name))
                self.table.setItem(row, 2, QTableWidgetItem("Sẵn sàng"))
                self.table.setItem(row, 3, QTableWidgetItem("Chưa xử lý"))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.btn_execute.setEnabled(len(self.target_files) > 0)

    def _view_selected_metadata(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.target_files):
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn 1 dòng trong bảng để xem.")
            return
        path = self.target_files[row]
        dlg = MetadataViewerDialog(path, parent=self)
        dlg.exec()

    def _start_strip(self):
        if not self.target_files:
            return

        reply = QMessageBox.question(
            self, "Xác nhận xóa Metadata",
            f"Bạn có chắc muốn xóa metadata của {len(self.target_files)} file?\n\n"
            + ("✅ Ngày tháng tạo file SẼ ĐƯỢC BẢO TOÀN." if self.chk_preserve_date.isChecked() else "⚠️ Ngày tháng tạo file SẼ BỊ XÓA."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_execute.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang xóa Metadata...", parent=self)
        self._progress_dlg.set_task("Đang xóa Metadata...", total=len(self.target_files), icon="🧹")

        self._worker = MetadataStripWorker(self.target_files)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.error.connect(self._on_error)

        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_progress(self, done: int, total: int, filename: str):
        self.lbl_status.setText(f"Đang xử lý ({done}/{total}): {filename}")

    def _on_finished(self, results: list):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn tất xóa metadata!")

        ok_count = 0
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            for row, res in enumerate(results):
                dt_str = res["date"].strftime("%d/%m/%Y %H:%M") if res.get("date") else "N/A"
                date_item = self.table.item(row, 2)
                if date_item:
                    date_item.setText(dt_str)
                else:
                    self.table.setItem(row, 2, QTableWidgetItem(dt_str))

                status_item = self.table.item(row, 3)
                if not status_item:
                    status_item = QTableWidgetItem()
                    self.table.setItem(row, 3, status_item)

                if res["success"]:
                    ok_count += 1
                    status_item.setText("✔ Đã xóa & bảo toàn")
                    status_item.setForeground(qcolor("success"))
                    status_item.setToolTip("Metadata đã được xóa sạch và ngày tạo được bảo toàn thành công.")
                else:
                    err_msg = res.get("error", "Lỗi không xác định")
                    status_item.setText(f"❌ {err_msg[:35]}")
                    status_item.setForeground(qcolor("danger"))
                    status_item.setToolTip(err_msg)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        self.lbl_status.setText(
            f"✅ Hoàn tất: {ok_count}/{len(results)} file thành công."
        )
        self.btn_execute.setEnabled(True)
        self.metadata_stripped.emit(results)

    def _on_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng xóa metadata.")

        self.btn_execute.setEnabled(True)
        self.lbl_status.setText("⚠️ Thao tác xóa metadata đã bị hủy.")
        QMessageBox.information(self, "Đã hủy", "Đã dừng tiến trình xóa metadata theo yêu cầu của bạn.")

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

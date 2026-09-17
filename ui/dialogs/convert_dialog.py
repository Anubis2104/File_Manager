"""
ui/dialogs/convert_dialog.py
Dialog for converting image/video files to different formats.
Output is always a copy in user-specified destination folder.
"""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Optional

from PyQt6.QtCore  import Qt, QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSlider, QTableWidget, QTableWidgetItem,
    QGroupBox, QFileDialog, QMessageBox,
    QHeaderView, QAbstractItemView, QCheckBox, QSpinBox,
)

from core.converter import ImageConverter, VideoConverter, SUPPORTED_IMAGE_EXTS, VIDEO_EXTS
from utils.file_utils import classify_extension
from ui.widgets.progress_dialog import TaskProgressDialog


IMAGE_FORMATS = [".jpg", ".png", ".webp", ".bmp", ".tiff", ".gif"]
VIDEO_FORMATS = [".mp4", ".avi", ".mkv", ".mov", ".webm"]


class ConvertWorker(QObject):
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(list)
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, jobs: list[dict], quality: int = 90, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.quality = quality
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            img_conv   = ImageConverter()
            vid_conv   = VideoConverter()
            results    = []
            total      = len(self.jobs)

            for i, job in enumerate(self.jobs):
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                src, dst = job["src"], job["dst"]
                media_type = classify_extension(src.suffix)

                if media_type == "image":
                    ok, err = img_conv.convert(src, dst, quality=self.quality)
                elif media_type == "video":
                    ok, err = vid_conv.convert(src, dst)
                else:
                    ok, err = False, "Unsupported file type"

                results.append({"src": src, "dst": dst, "success": ok, "error": err})
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                self.progress.emit(i + 1, total, src.name)

            if self.is_cancelled:
                self.cancelled.emit()
                return
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class ConvertDialog(QDialog):
    """
    Format conversion dialog.
    User selects source files, target format, output folder, quality.
    Converts as COPY, never overwrites originals.
    """

    def __init__(self, files: Optional[list[Path]] = None, folder: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.input_files: list[Path] = list(files) if files else []
        if folder and folder.is_dir():
            for file_path in folder.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in (SUPPORTED_IMAGE_EXTS | VIDEO_EXTS):
                    if file_path not in self.input_files:
                        self.input_files.append(file_path)

        self._thread: Optional[QThread] = None
        self._worker: Optional[ConvertWorker] = None

        self.setWindowTitle("Chuyển đổi định dạng hàng loạt")
        self.setMinimumSize(860, 540)
        self._build_ui()

        if self.input_files:
            self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Input files ──
        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("File nguồn:"))
        self.lbl_count = QLabel("0 file")
        self.lbl_count.setStyleSheet("color: #0a84ff; font-weight: 600;")
        in_row.addWidget(self.lbl_count)
        in_row.addStretch()

        btn_add_folder = QPushButton("📁  Thêm thư mục (Đệ quy)")
        btn_add_folder.setToolTip("Quét đệ quy toàn bộ thư mục con để nạp tất cả ảnh/video")
        btn_add_folder.clicked.connect(self._add_folder)
        in_row.addWidget(btn_add_folder)

        btn_add = QPushButton("➕  Thêm file")
        btn_add.clicked.connect(self._add_files)
        in_row.addWidget(btn_add)

        btn_clear = QPushButton("🗑  Xóa hết")
        btn_clear.clicked.connect(self._clear_files)
        in_row.addWidget(btn_clear)
        layout.addLayout(in_row)

        # ── Format settings ──
        fmt_group = QGroupBox("Cài đặt chuyển đổi")
        fmt_layout = QHBoxLayout(fmt_group)

        fmt_layout.addWidget(QLabel("Định dạng đích:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems([f.upper().replace(".", "") for f in IMAGE_FORMATS + VIDEO_FORMATS])
        self.fmt_combo.setFixedWidth(100)
        fmt_layout.addWidget(self.fmt_combo)

        fmt_layout.addWidget(QLabel("  Chất lượng (%):"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(10, 100)
        self.quality_spin.setValue(90)
        self.quality_spin.setFixedWidth(65)
        fmt_layout.addWidget(self.quality_spin)

        fmt_layout.addWidget(QLabel("  Thư mục đích:"))
        self.dst_edit = QLineEdit()
        self.dst_edit.setPlaceholderText("Để trống = cùng thư mục với file gốc")
        fmt_layout.addWidget(self.dst_edit)

        btn_browse_dst = QPushButton("📁")
        btn_browse_dst.setFixedWidth(32)
        btn_browse_dst.clicked.connect(self._browse_dst)
        fmt_layout.addWidget(btn_browse_dst)
        layout.addWidget(fmt_group)

        # ── Preview table ──
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["File nguồn", "Loại", "File đích (dự kiến)"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)


        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_convert = QPushButton("🔄  Bắt đầu chuyển đổi")
        self.btn_convert.setObjectName("btnPrimary")
        self.btn_convert.clicked.connect(self._start_convert)
        btn_row.addWidget(self.btn_convert)
        layout.addLayout(btn_row)

        # Connect format change → refresh table
        self.fmt_combo.currentTextChanged.connect(self._populate_table)
        self.dst_edit.textChanged.connect(self._populate_table)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn file", "",
            "Media files (*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.gif "
            "*.mp4 *.avi *.mkv *.mov *.webm);;All Files (*)"
        )
        for p in paths:
            path = Path(p)
            if path not in self.input_files:
                self.input_files.append(path)
        self._populate_table()

    def _add_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa ảnh/video (duyệt đệ quy)")
        if dir_path:
            p = Path(dir_path)
            for file_path in p.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in (SUPPORTED_IMAGE_EXTS | VIDEO_EXTS):
                    if file_path not in self.input_files:
                        self.input_files.append(file_path)
            self._populate_table()

    def _clear_files(self):
        self.input_files.clear()
        self.table.setRowCount(0)
        self.lbl_count.setText("0 file")

    def _browse_dst(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục đích")
        if folder:
            self.dst_edit.setText(folder)

    def _populate_table(self):
        ext = "." + self.fmt_combo.currentText().lower()
        dst_folder = self.dst_edit.text().strip()
        self.table.setRowCount(len(self.input_files))
        self.lbl_count.setText(f"{len(self.input_files)} file")

        for row, src in enumerate(self.input_files):
            if dst_folder:
                dst = Path(dst_folder) / (src.stem + ext)
            else:
                dst = src.parent / (src.stem + ext)
            media_type = classify_extension(src.suffix)

            self.table.setItem(row, 0, QTableWidgetItem(src.name))
            self.table.setItem(row, 1, QTableWidgetItem(media_type))
            self.table.setItem(row, 2, QTableWidgetItem(str(dst)))

    def _build_jobs(self) -> list[dict]:
        ext = "." + self.fmt_combo.currentText().lower()
        dst_folder = self.dst_edit.text().strip()
        jobs = []
        for src in self.input_files:
            if dst_folder:
                dst = Path(dst_folder) / (src.stem + ext)
            else:
                dst = src.parent / (src.stem + ext)
            jobs.append({"src": src, "dst": dst})
        return jobs

    def _start_convert(self):
        jobs = self._build_jobs()
        if not jobs:
            return
        self.btn_convert.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang chuyển đổi định dạng...", parent=self)
        self._progress_dlg.set_task("Đang chuyển đổi định dạng...", total=len(jobs), icon="🔄")

        self._worker = ConvertWorker(jobs, quality=self.quality_spin.value())
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.progress.connect(
            lambda d, t, n: self.lbl_status.setText(f"Đang chuyển đổi: {n}  ({d}/{t})")
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.error.connect(self._on_error)

        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_finished(self, results: list):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn tất chuyển đổi!")

        ok = sum(1 for r in results if r["success"])
        fail = len(results) - ok
        self.lbl_status.setText(
            f"✅ {ok} file thành công"
            + (f"  ❌ {fail} lỗi" if fail else "")
        )
        self.btn_convert.setEnabled(True)

    def _on_cancelled(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng chuyển đổi.")

        self.btn_convert.setEnabled(True)
        self.lbl_status.setText("⚠️ Tiến trình chuyển đổi đã bị hủy.")
        QMessageBox.information(self, "Đã hủy", "Đã dừng chuyển đổi theo yêu cầu của bạn.")

    def _on_error(self, err_msg: str):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_convert.setEnabled(True)
        QMessageBox.critical(self, "Lỗi", err_msg)

    def closeEvent(self, event):
        if hasattr(self, "_worker") and self._worker:
            self._worker.cancel()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(300)
        super().closeEvent(event)

"""
ui/widgets/progress_dialog.py
Standardized Modal Progress Popup Dialog with Cancel button.
Used across all long-running background operations in FileManagerPro:
- Queue Renaming
- Batch Renaming
- Directory Scanning
- Duplicate Detection
- Metadata Stripping
- Format Conversion
- Empty Folder Cleaning
- Byte Inspector
"""
from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QWidget,
)
from ui.theme import style


class TaskProgressDialog(QDialog):
    """
    Standardized Modal Popup Dialog with progress bar and cancel button.
    Emits `cancelled` signal when user clicks Cancel.
    """
    cancelled = pyqtSignal()

    def __init__(self, title: str = "Đang xử lý...", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setFixedHeight(190)

        # Remove help button from title bar
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )

        self._total = 100
        self._current = 0
        self._is_cancelled = False

        self._build_ui(title)

    def _build_ui(self, title: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # ── Header: Icon + Title ──
        hdr_lay = QHBoxLayout()
        hdr_lay.setSpacing(10)

        self.lbl_icon = QLabel("🔄")
        self.lbl_icon.setStyleSheet("font-size: 20px;")
        hdr_lay.addWidget(self.lbl_icon)

        self.lbl_title = QLabel(title)
        style(self.lbl_title, "font-size: 11pt; font-weight: 700; color: @text_primary;")
        hdr_lay.addWidget(self.lbl_title)
        hdr_lay.addStretch()

        layout.addLayout(hdr_lay)

        # ── Status Message & File Name ──
        self.lbl_status = QLabel("Đang chuẩn bị...")
        style(self.lbl_status, "color: @text_secondary; font-size: 9pt;")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # ── Progress Bar ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style(self.progress_bar, 
            "QProgressBar { background-color: @fill_hover; border: 1px solid @stroke_control; "
            "border-radius: 8px; text-align: center; color: @text_primary; font-size: 8pt; font-weight: bold; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 @accent, stop:1 @success); border-radius: 7px; }"
        )
        layout.addWidget(self.progress_bar)

        # ── Footer: Counter info + Cancel Button ──
        footer_lay = QHBoxLayout()

        self.lbl_counter = QLabel("0 / 0 (0%)")
        style(self.lbl_counter, "color: @text_secondary; font-size: 8.5pt;")
        footer_lay.addWidget(self.lbl_counter)
        footer_lay.addStretch()

        self.btn_cancel = QPushButton("✕  Hủy bỏ")
        self.btn_cancel.setFixedHeight(28)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        style(self.btn_cancel, 
            "QPushButton { background: @fill_selected; color: @danger; border: 1px solid @stroke_control; "
            "border-radius: 5px; padding: 2px 14px; font-size: 8.5pt; font-weight: 600; }"
            "QPushButton:hover { background: @danger; color: @text_on_accent; border-color: @danger; }"
            "QPushButton:disabled { background: @fill_hover; color: @text_tertiary; border-color: @stroke_control; }"
        )
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        footer_lay.addWidget(self.btn_cancel)

        layout.addLayout(footer_lay)

        # Default dark dialog style
        self.setObjectName("TaskProgressDialog")
        self.setAutoFillBackground(True)
        style(self, 
            "#TaskProgressDialog, QDialog { background-color: @bg_base; color: @text_primary; border: 1px solid @stroke_control; border-radius: 8px; }\n"
            "QLabel { background: transparent; }"
        )

    def show_centered(self):
        """Center the dialog relative to its parent or active window and show modally."""
        parent_w = self.parent()
        if parent_w:
            win = parent_w.window() if hasattr(parent_w, "window") else parent_w
            geo = win.geometry()
            x = geo.x() + max(0, (geo.width() - self.width()) // 2)
            y = geo.y() + max(0, (geo.height() - self.height()) // 2)
            self.move(x, y)
        self.show()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def set_indeterminate(self, status_text: str = "Đang xử lý..."):
        """Switch progress bar into infinite indeterminate animation mode."""
        self.progress_bar.setRange(0, 0)
        self.lbl_counter.setText("Đang xử lý...")
        if status_text:
            self.lbl_status.setText(status_text)

    def set_task(self, title: str, total: int = 100, icon: str = "🔄"):
        """Configure dialog task parameters."""
        self._total = max(1, total)
        self._current = 0
        self._is_cancelled = False
        self.setWindowTitle(title)
        self.lbl_title.setText(title)
        self.lbl_icon.setText(icon)
        self.progress_bar.setRange(0, self._total)
        self.progress_bar.setValue(0)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("✕  Hủy bỏ")
        self.lbl_counter.setText(f"0 / {self._total} (0%)")

    def update_progress(self, current: int, total: int = 0, status_text: str = ""):
        """Update progress bar, current item text, and counters."""
        if self._is_cancelled:
            return
        if total > 0:
            self._total = total
            self.progress_bar.setRange(0, total)
        self._current = current
        self.progress_bar.setValue(current)

        pct = int((current / self._total) * 100) if self._total > 0 else 0
        self.lbl_counter.setText(f"{current} / {self._total} ({pct}%)")

        if status_text:
            display_text = status_text if len(status_text) <= 55 else (status_text[:52] + "...")
            self.lbl_status.setText(f"Đang xử lý: {display_text}")

    def attach_worker(self, worker):
        """
        Securely bind a background worker to this progress dialog.
        Cancellation is directly wired with Qt.ConnectionType.DirectConnection so
        worker.cancel() executes instantly on the GUI thread when the user clicks 'Hủy bỏ'.
        """
        self._worker_ref = worker
        if hasattr(worker, "cancel"):
            try:
                self.cancelled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)
            except Exception:
                pass

    def finish_task(self, success_message: str = "Hoàn tất!"):
        """Indicate task completion and close dialog."""
        self.lbl_status.setText(success_message)
        self.lbl_icon.setText("✅")
        self.progress_bar.setValue(self._total)
        self.btn_cancel.setEnabled(False)
        self.accept()

    def cancel_task(self, reason: str = "Đã dừng thao tác"):
        """Indicate task cancelled and close."""
        self._is_cancelled = True
        self.lbl_status.setText(reason)
        self.lbl_icon.setText("⚠️")
        self.btn_cancel.setEnabled(False)
        self.reject()

    def _on_cancel_clicked(self):
        """User pressed cancel button."""
        self._is_cancelled = True
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("Đang hủy...")
        self.lbl_status.setText("⏳ Đang dừng tiến trình, vui lòng đợi...")
        if getattr(self, "_worker_ref", None) is not None:
            try:
                self._worker_ref.cancel()
            except Exception:
                pass
        self.cancelled.emit()

    def reject(self):
        """If user closes via Escape key or reject(), trigger cancel."""
        if not self._is_cancelled and self.btn_cancel.isEnabled():
            self._on_cancel_clicked()
        super().reject()

    def closeEvent(self, event):
        """If user closes window via Alt+F4 or window X, trigger cancel."""
        if not self._is_cancelled and self.btn_cancel.isEnabled():
            self._on_cancel_clicked()
        event.accept()

"""
ui/widgets/progress_banner.py
A modern, animated progress banner that docks neatly above the status bar.
Displays operation title, percentage, file count, throughput speed (file/s), ETA, and Cancel button.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore  import Qt, QTimer, pyqtSignal
from PyQt6.QtGui   import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QProgressBar, QPushButton, QFrame, QSizePolicy,
)


class ProgressBanner(QFrame):
    """
    Sleek task progress banner for file scanning, renaming, converting, and AI scanning.
    """
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("progressBanner")
        self._start_time: float = 0.0
        self._last_count: int = 0
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setStyleSheet("""
            QFrame#progressBanner {
                background-color: #252528;
                border-top: 1px solid #3a3a3c;
                border-bottom: 1px solid #3a3a3c;
                padding: 6px 12px;
            }
            QLabel#lblTaskTitle {
                color: #ffffff;
                font-weight: 600;
                font-size: 9pt;
            }
            QLabel#lblDetails {
                color: #8e8e93;
                font-size: 8.5pt;
            }
            QProgressBar#mainProgress {
                border: none;
                border-radius: 3px;
                background-color: #3a3a3c;
                height: 6px;
                text-align: right;
            }
            QProgressBar#mainProgress::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a84ff, stop:1 #5ac8fa);
                border-radius: 3px;
            }
            QPushButton#btnCancelTask {
                background-color: #3a3a3c;
                color: #ff453a;
                border: 1px solid #ff453a44;
                border-radius: 5px;
                font-size: 8.5pt;
                font-weight: 600;
                padding: 3px 10px;
            }
            QPushButton#btnCancelTask:hover {
                background-color: #ff453a22;
                border-color: #ff453a;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        # Top row: Title, current file, metrics, and Cancel button
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Task icon & title
        self.lbl_title = QLabel("Đang xử lý...")
        self.lbl_title.setObjectName("lblTaskTitle")
        top_row.addWidget(self.lbl_title)

        # Current file name
        self.lbl_current_file = QLabel("")
        self.lbl_current_file.setObjectName("lblDetails")
        self.lbl_current_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.lbl_current_file)

        # Metrics (Count, Speed, ETA)
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setObjectName("lblDetails")
        self.lbl_metrics.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.lbl_metrics)

        # Cancel button
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setObjectName("btnCancelTask")
        self.btn_cancel.setFixedWidth(70)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        top_row.addWidget(self.btn_cancel)

        layout.addLayout(top_row)

        # Bottom row: Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("mainProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

    def start_task(self, title: str, total: int = 0, cancellable: bool = True):
        """Initialize and display the progress banner."""
        self._start_time = time.time()
        self._last_count = 0
        self.lbl_title.setText(title)
        self.lbl_current_file.setText("Khởi tạo...")
        self.lbl_metrics.setText("")
        self.btn_cancel.setVisible(cancellable)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("Hủy")

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
        else:
            self.progress_bar.setRange(0, 0) # Indeterminate mode

        self.show()

    def update_progress(self, current: int, total: int = 0, current_item: str = ""):
        """Update progress value, current file display, speed, and ETA."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            pct = (current / total) * 100
        else:
            pct = 0

        # Truncate filename nicely
        if current_item:
            display_name = current_item if len(current_item) < 45 else "..." + current_item[-42:]
            self.lbl_current_file.setText(f"{display_name}")

        # Compute speed & ETA
        elapsed = time.time() - self._start_time
        if elapsed > 0.3 and current > 0:
            speed = current / elapsed
            if total > 0 and speed > 0:
                remaining = max(0, total - current)
                eta_secs = int(remaining / speed)
                eta_str = f"còn ~{eta_secs}s" if eta_secs < 60 else f"còn ~{eta_secs//60}m {eta_secs%60}s"
                self.lbl_metrics.setText(
                    f"{current:,} / {total:,} ({pct:.1f}%) • {speed:.0f} file/s • {eta_str}"
                )
            else:
                self.lbl_metrics.setText(f"{current:,} mục • {speed:.0f} file/s")
        else:
            if total > 0:
                self.lbl_metrics.setText(f"{current:,} / {total:,} ({pct:.1f}%)")
            else:
                self.lbl_metrics.setText(f"{current:,} mục")

    def finish_task(self, success_msg: str = "Hoàn tất!"):
        """Display success state and auto-hide after 2.5s."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_title.setText(f"{success_msg}")
        self.lbl_current_file.setText("")
        self.lbl_metrics.setText("")
        self.btn_cancel.hide()
        QTimer.singleShot(2500, self.hide)

    def cancel_task(self, cancel_msg: str = "Đã hủy tác vụ."):
        """Display cancelled state and hide."""
        self.lbl_title.setText(f"{cancel_msg}")
        self.lbl_current_file.setText("")
        self.lbl_metrics.setText("")
        self.btn_cancel.hide()
        QTimer.singleShot(1800, self.hide)

    def _on_cancel_clicked(self):
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("Đang dừng...")
        self.lbl_current_file.setText("Đang gửi tín hiệu dừng luồng...")
        self.cancelled.emit()

"""
ui/widgets/statusbar.py
Custom status bar: file count, CUDA info, progress.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore    import Qt
from PyQt6.QtWidgets import QStatusBar, QLabel, QWidget, QHBoxLayout
from ui.theme import style


class AppStatusBar(QStatusBar):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_widgets()

    def _build_widgets(self):
        # Left: path info
        self.lbl_path = QLabel("Sẵn sàng")
        style(self.lbl_path, "color: @text_secondary; font-size: 8.5pt;")
        self.addWidget(self.lbl_path, 1)

        # Center: selection info
        self.lbl_selection = QLabel("")
        style(self.lbl_selection, "color: @text_tertiary; font-size: 8.5pt;")
        self.addWidget(self.lbl_selection, 1)

        # Right: CUDA badge
        self.lbl_cuda = QLabel()
        style(self.lbl_cuda, 
            "background: #30d15822; color: @success; border: 1px solid #30d15844; "
            "border-radius: 4px; padding: 1px 8px; font-size: 8pt; font-weight: 600;"
        )
        self.addPermanentWidget(self.lbl_cuda)

        # Progress (deprecated; no-op for backward compatibility)
        self.progress = None

    def set_path(self, path: Path):
        self.lbl_path.setText(f"  {path}")

    def set_cuda_info(self, info_str: str):
        if "Not available" in info_str or "missing" in info_str:
            self.lbl_cuda.setText("CPU Mode")
            style(self.lbl_cuda, 
                "background: #ff9f0a22; color: @warning; border: 1px solid #ff9f0a44; "
                "border-radius: 4px; padding: 1px 8px; font-size: 8pt; font-weight: 600;"
            )
        else:
            # Extract GPU name
            name_part = info_str.split("|")[0].replace("CUDA:", "").strip()
            self.lbl_cuda.setText(f"GPU: {name_part}")

    def update_selection(self, selected_paths: list):
        if not selected_paths:
            self.lbl_selection.setText("")
        else:
            n = len(selected_paths)
            self.lbl_selection.setText(f"{n} mục đã chọn")

    def show_progress(self, value: int, maximum: int):
        """Deprecated; no-op. Progress is displayed in TaskProgressDialog."""
        pass

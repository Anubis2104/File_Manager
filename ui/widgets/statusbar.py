"""
ui/widgets/statusbar.py
Explorer status bar:  "12 mục   |   3 mục được chọn  4,21 MB"  ...  [details] [large icons]

`lbl_path` is kept as the transient message label other code writes scan/copy status to.
The compute badge (GPU / CPU) is plain secondary text instead of a colored chip.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QLocale, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QStatusBar, QToolButton

from ui.shell import glyph_font
from ui.theme import style

GLYPH_DETAILS, GLYPH_LARGE_ICONS = "", ""
MAX_SIZED_SELECTION = 1000

_TOGGLE_QSS = (
    "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; "
    "color: @text_secondary; padding: 0px; }"
    "QToolButton:hover { background: @fill_hover; }"
    "QToolButton:checked { background: @fill_selected; border-color: @stroke_control; color: @text_primary; }"
)


def explorer_bytes(size: int) -> str:
    """'4,21 MB' / '980 KB' / '12 bytes' like Explorer's status bar and selection info."""
    loc = QLocale.system()
    if size < 1024:
        return f"{size} bytes"
    for unit, div in (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3), ("TB", 1024 ** 4)):
        value = size / div
        if value < 1024 or unit == "TB":
            decimals = 0 if value >= 100 else (1 if value >= 10 else 2)
            return f"{loc.toString(value, 'f', decimals)} {unit}"
    return f"{size} bytes"


class AppStatusBar(QStatusBar):
    view_requested = pyqtSignal(str)     # "detail" | "large"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self._build_widgets()

    def _build_widgets(self):
        self.lbl_items = QLabel("")
        self.lbl_selection = QLabel("")
        self.lbl_path = QLabel("")           # transient messages (scan / copy / errors)
        for lbl in (self.lbl_items, self.lbl_selection, self.lbl_path):
            style(lbl, "color: @text_secondary; padding: 0px 8px;")
        self.addWidget(self.lbl_items)
        self.addWidget(self.lbl_selection)
        self.addWidget(self.lbl_path, 1)

        self.lbl_cuda = QLabel()
        style(self.lbl_cuda, "color: @text_tertiary; padding: 0px 8px;")
        self.addPermanentWidget(self.lbl_cuda)

        self.btn_details = self._toggle(GLYPH_DETAILS, "Chi tiết (Ctrl+Shift+6)", "detail")
        self.btn_large = self._toggle(GLYPH_LARGE_ICONS, "Biểu tượng lớn (Ctrl+Shift+2)", "large")
        self.progress = None                 # deprecated; kept for backward compatibility

    def _toggle(self, glyph: str, tip: str, mode: str) -> QToolButton:
        b = QToolButton()
        b.setText(glyph)
        b.setFont(glyph_font(12))
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setFixedSize(24, 20)
        style(b, _TOGGLE_QSS)
        b.clicked.connect(lambda: self.view_requested.emit(mode))
        self.addPermanentWidget(b)
        return b

    # ── state ──

    def set_path(self, path: Path):
        self.lbl_path.setText("")            # Explorer shows the location in the address bar only

    def set_item_count(self, n: int):
        self.lbl_items.setText(f"{n} mục")

    def update_selection(self, selected_paths: list):
        if not selected_paths:
            self.lbl_selection.setText("")
            return
        n = len(selected_paths)
        text = f"{n} mục được chọn"
        if n > MAX_SIZED_SELECTION:          # don't stat thousands of files on the UI thread
            self.lbl_selection.setText(text)
            return
        files = [Path(p) for p in selected_paths if Path(p).is_file()]
        if files and len(files) == n:        # Explorer shows a size only when no folder is selected
            try:
                text += f"   {explorer_bytes(sum(p.stat().st_size for p in files))}"
            except OSError:
                pass
        self.lbl_selection.setText(text)

    def set_view_mode(self, mode: str):
        self.btn_details.setChecked(mode == "detail")
        self.btn_large.setChecked(mode == "large")

    def set_cuda_info(self, info_str: str):
        if "Not available" in info_str or "missing" in info_str:
            self.lbl_cuda.setText("CPU")
            tip = "Không có GPU CUDA — tìm trùng lặp bằng AI chạy trên CPU"
            reason = info_str.partition(" — ")[2]
            self.lbl_cuda.setToolTip(f"{tip}\n{reason}" if reason else tip)
        else:
            name_part = info_str.split("|")[0].replace("CUDA:", "").strip()
            self.lbl_cuda.setText(f"GPU: {name_part}")
            self.lbl_cuda.setToolTip(info_str)

    def show_progress(self, value: int, maximum: int):
        """Deprecated; no-op. Progress is displayed in TaskProgressDialog."""
        pass

"""
ui/widgets/title_bar.py
Explorer-style title bar: the tab strip on the left, then draggable empty space.

The minimize / maximize / close buttons are not widgets: DWM draws the real ones in
the top-right corner (see ui/win_chrome.py), so the bar only reserves their width.
Background is transparent so the window's Mica backdrop shows through.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from ui.theme import style

TITLE_BAR_HEIGHT = 40


class TitleBar(QWidget):
    """Hosts the tab strip for a window using WindowChrome."""

    def __init__(self, window: QWidget, tab_strip: QWidget, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        style(self, "#titleBar { background: transparent; }")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(0)

        self.tab_strip = tab_strip
        tab_strip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(tab_strip, 0, Qt.AlignmentFlag.AlignBottom)

        self.drag_area = QWidget()   # empty space → HTCAPTION
        self.drag_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.drag_area, 1)

        # Room for the DWM-drawn caption buttons
        self.caption_space = QWidget()
        self.caption_space.setFixedWidth(0)
        lay.addWidget(self.caption_space)

    def set_caption_width(self, width: int) -> None:
        self.caption_space.setFixedWidth(max(0, width))

    def mouseDoubleClickEvent(self, event):
        # Fallback when native hit-testing is unavailable (non-Windows / chrome not installed)
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.window_ref
            w.showNormal() if w.isMaximized() else w.showMaximized()
        super().mouseDoubleClickEvent(event)

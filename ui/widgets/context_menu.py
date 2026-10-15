"""
ui/widgets/context_menu.py
Windows 11 style context menu: a row of icon buttons on top (Cut, Copy, Paste, Rename,
Share, Delete — whichever apply), then regular entries, ending with
"Hiện thêm tùy chọn" (Show more options), which opens the real Shell menu.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget, QWidgetAction

from ui.theme import style
from ui.widgets.command_bar import GLYPH, glyph_icon

GLYPH.setdefault("share", "")
GLYPH.setdefault("open", "")
GLYPH.setdefault("more_options", "")
GLYPH.setdefault("properties", "")
GLYPH.setdefault("copy_path", "")
GLYPH.setdefault("pin", "")

_ROW_BUTTON_QSS = (
    "QToolButton { background: transparent; border: none; border-radius: 4px; padding: 6px; }"
    "QToolButton:hover { background: @fill_hover; }"
    "QToolButton:pressed { background: @fill_pressed; }"
)

QuickVerb = tuple[str, str, Callable[[], None]]      # (glyph key, tooltip, action)


class ExplorerContextMenu(QMenu):
    """QMenu with Windows 11's quick-action icon row."""

    def __init__(self, quick_verbs: Sequence[QuickVerb] = (), parent=None):
        super().__init__(parent)
        self.quick_buttons: dict[str, QToolButton] = {}
        if quick_verbs:
            row = QWidget(self)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(6, 4, 6, 4)
            lay.setSpacing(2)
            for key, tip, fn in quick_verbs:
                b = QToolButton(row)
                b.setIcon(glyph_icon(GLYPH[key]))
                b.setIconSize(QSize(16, 16))
                b.setToolTip(tip)
                b.setAccessibleName(tip)
                b.setAutoRaise(True)
                style(b, _ROW_BUTTON_QSS)
                b.clicked.connect(lambda _=False, f=fn: (self.close(), f()))
                lay.addWidget(b)
                self.quick_buttons[key] = b
            lay.addStretch(1)
            wa = QWidgetAction(self)
            wa.setDefaultWidget(row)
            self.addAction(wa)
            self.addSeparator()

    def add(self, glyph: Optional[str], text: str, fn: Callable[[], None], shortcut: str = ""):
        act = self.addAction(glyph_icon(GLYPH[glyph]) if glyph else glyph_icon(" "), text)
        if shortcut:
            act.setShortcut(shortcut)
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)   # display only
            act.setShortcutVisibleInContextMenu(True)
        act.triggered.connect(fn)
        return act

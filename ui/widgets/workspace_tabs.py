"""
ui/widgets/workspace_tabs.py
Browser-style Multi-Tab Workspace Bar for FileManagerPro.
Provides Chrome / Windows 11 Explorer style tabs:
- [ 📁 Folder Name   ✕ ] tabs with active highlight
- [ + ] New Tab button
- Context menu (Close, Close Others, Duplicate, Copy Path)
- Middle-click to close
- Ctrl+T (New Tab), Ctrl+W (Close Tab), Ctrl+Tab (Cycle Tabs)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QIcon, QAction, QCursor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QScrollArea, QFrame, QMenu, QApplication, QSizePolicy,
)
from PyQt6.QtCore import QFileInfo
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFileIconProvider

from ui.theme import style

TAB_HEIGHT = 34
GLYPH_CLOSE, GLYPH_ADD = "", ""   # Segoe Fluent Icons

_icon_provider: Optional[QFileIconProvider] = None


def _shell_icon(path: Path) -> QIcon:
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    return _icon_provider.icon(QFileInfo(str(path)))


def _glyph_font(px: int) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    f.setPixelSize(px)
    return f


class TabItemData:
    """Stores navigation state for a single workspace tab."""
    def __init__(self, path: Path):
        self.path = path
        self.history: list[Path] = [path]
        self.history_idx: int = 0
        self.search_query: str = ""

    @property
    def title(self) -> str:
        if self.path == Path.home():
            return "Home"
        name = self.path.name
        return name if name else str(self.path)


class WorkspaceTabButton(QFrame):
    """Visual tab button with icon, folder title, and close button."""
    clicked = pyqtSignal(int)
    close_clicked = pyqtSignal(int)
    middle_clicked = pyqtSignal(int)
    context_menu_requested = pyqtSignal(int, QPoint)

    def __init__(self, index: int, data: TabItemData, is_active: bool = False, parent=None):
        super().__init__(parent)
        self.index = index
        self.data = data
        self.is_active = is_active
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        self.setObjectName("workspaceTab")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TAB_HEIGHT)
        self.setMinimumWidth(140)
        self.setMaximumWidth(240)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(8)

        # Shell icon (Pictures, Downloads, drives... look exactly like in Explorer)
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(16, 16)
        lay.addWidget(self.lbl_icon)

        self.lbl_title = QLabel()
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_title)

        self.btn_close = QToolButton()
        self.btn_close.setText(GLYPH_CLOSE)
        self.btn_close.setFont(_glyph_font(9))
        self.btn_close.setToolTip("Đóng tab (Ctrl+W)")
        self.btn_close.setFixedSize(24, 24)
        style(self.btn_close,
            "QToolButton { background: transparent; border: none; border-radius: 4px; color: @text_primary; }"
            "QToolButton:hover { background: @hover_on_mica; }"
        )
        self.btn_close.clicked.connect(lambda: self.close_clicked.emit(self.index))
        lay.addWidget(self.btn_close)
        self.set_data(self.data)

    def set_active(self, active: bool):
        self.is_active = active
        self._apply_style()

    def set_data(self, data: TabItemData):
        self.data = data
        self.lbl_title.setText(data.title)
        self.setToolTip(str(data.path))
        self.lbl_icon.setPixmap(_shell_icon(data.path).pixmap(16, 16))

    def _apply_style(self):
        # Explorer: the active tab is the same translucent layer as the address row
        # below it, so the two read as one surface; inactive tabs sit on bare Mica.
        if self.is_active:
            style(self,
                "#workspaceTab { background: @layer_on_mica; border: none; "
                "border-top-left-radius: 8px; border-top-right-radius: 8px; }"
            )
        else:
            style(self,
                "#workspaceTab { background: transparent; border: none; border-radius: 6px; }"
                "#workspaceTab:hover { background: @hover_on_mica; }"
            )
        style(self.lbl_title, "background: transparent; color: @text_primary;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.middle_clicked.emit(self.index)
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(self.index, event.globalPosition().toPoint())
        super().mousePressEvent(event)


class WorkspaceTabBar(QWidget):
    """
    Horizontal tab container bar with browser-like tabs and a '+' button.
    """
    tab_switched = pyqtSignal(int, Path)   # (tab_index, current_path)
    tab_closed = pyqtSignal(int)           # closed index
    new_tab_requested = pyqtSignal(Path)    # Path to open in new tab

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs: list[TabItemData] = []
        self.active_index: int = -1
        self._buttons: list[WorkspaceTabButton] = []
        self._build_ui()

    def _build_ui(self):
        # Lives in the title bar: transparent so the window's Mica backdrop shows through
        self.setFixedHeight(TAB_HEIGHT + 6)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        style(self, "WorkspaceTabBar { background: transparent; }")

        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(0, 6, 0, 0)
        main_lay.setSpacing(4)

        # Scrollable container for tabs
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.scroll.viewport().setAutoFillBackground(False)

        self.tab_container = QWidget()
        self.tab_container.setStyleSheet("background: transparent;")
        self.tabs_layout = QHBoxLayout(self.tab_container)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(2)
        self.tabs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        self.scroll.setWidget(self.tab_container)
        main_lay.addWidget(self.scroll)

        # New Tab Button [+]
        self.btn_new_tab = QToolButton()
        self.btn_new_tab.setText(GLYPH_ADD)
        self.btn_new_tab.setFont(_glyph_font(11))
        self.btn_new_tab.setToolTip("Mở tab mới (Ctrl+T)")
        self.btn_new_tab.setFixedSize(32, 30)
        style(self.btn_new_tab,
            "QToolButton { background: transparent; border: none; border-radius: 6px; color: @text_primary; } "
            "QToolButton:hover { background: @hover_on_mica; }"
        )
        self.btn_new_tab.clicked.connect(self._on_new_tab_clicked)
        main_lay.addWidget(self.btn_new_tab, 0, Qt.AlignmentFlag.AlignVCenter)

    def sizeHint(self) -> QSize:
        # Grow with the tabs so the title bar keeps the rest as drag space
        tabs_w = sum(b.sizeHint().width() + 2 for b in self._buttons) if self._buttons else 0
        return QSize(min(tabs_w, 1200) + 40, TAB_HEIGHT + 6)

    def add_tab(self, path: Optional[Path] = None, make_active: bool = True) -> int:
        """Add a new tab pointing to path (defaults to Home or current active path)."""
        if path is None:
            if self.tabs and 0 <= self.active_index < len(self.tabs):
                path = self.tabs[self.active_index].path
            else:
                path = Path.home()

        data = TabItemData(path)
        self.tabs.append(data)
        new_idx = len(self.tabs) - 1

        self._rebuild_tab_buttons()
        if make_active:
            self.switch_to_tab(new_idx)
        return new_idx

    def close_tab(self, index: int):
        """Close tab at index. If only 1 tab left, resets it to Home."""
        if len(self.tabs) <= 1:
            # Keep at least 1 tab open, reset to home
            self.tabs[0].path = Path.home()
            self._rebuild_tab_buttons()
            self.tab_switched.emit(0, Path.home())
            return

        if 0 <= index < len(self.tabs):
            self.tabs.pop(index)
            if self.active_index >= len(self.tabs):
                self.active_index = len(self.tabs) - 1
            elif self.active_index > index:
                self.active_index -= 1

            self._rebuild_tab_buttons()
            self.tab_switched.emit(self.active_index, self.tabs[self.active_index].path)
            self.tab_closed.emit(index)

    def switch_to_tab(self, index: int):
        """Make tab at index active."""
        if 0 <= index < len(self.tabs):
            self.active_index = index
            for i, btn in enumerate(self._buttons):
                btn.set_active(i == index)
            self.tab_switched.emit(index, self.tabs[index].path)

    def update_active_tab_path(self, path: Path):
        """Called when user navigates inside the active tab."""
        if 0 <= self.active_index < len(self.tabs):
            tab = self.tabs[self.active_index]
            tab.path = path
            if self._buttons and self.active_index < len(self._buttons):
                self._buttons[self.active_index].set_data(tab)

    def get_active_tab(self) -> Optional[TabItemData]:
        if 0 <= self.active_index < len(self.tabs):
            return self.tabs[self.active_index]
        return None

    def cycle_tab(self, delta: int = 1):
        """Cycle to next (delta=1) or previous (delta=-1) tab."""
        if not self.tabs:
            return
        next_idx = (self.active_index + delta) % len(self.tabs)
        self.switch_to_tab(next_idx)

    def _rebuild_tab_buttons(self):
        # Clear existing buttons
        while self.tabs_layout.count():
            item = self.tabs_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._buttons.clear()

        # Re-populate
        for i, data in enumerate(self.tabs):
            btn = WorkspaceTabButton(i, data, is_active=(i == self.active_index), parent=self)
            btn.clicked.connect(self.switch_to_tab)
            btn.close_clicked.connect(self.close_tab)
            btn.middle_clicked.connect(self.close_tab)
            btn.context_menu_requested.connect(self._show_context_menu)
            self.tabs_layout.addWidget(btn)
            self._buttons.append(btn)
        self.updateGeometry()

    def _on_new_tab_clicked(self):
        current_path = self.tabs[self.active_index].path if self.tabs else Path.home()
        self.new_tab_requested.emit(current_path)

    def _show_context_menu(self, index: int, global_pos: QPoint):
        if not (0 <= index < len(self.tabs)):
            return
        tab_data = self.tabs[index]
        menu = QMenu(self)

        act_new = menu.addAction("➕  Mở Tab mới (Ctrl+T)")
        act_new.triggered.connect(lambda: self.new_tab_requested.emit(tab_data.path))

        act_dup = menu.addAction("📑  Nhân bản Tab này")
        act_dup.triggered.connect(lambda: self.add_tab(tab_data.path))

        menu.addSeparator()

        act_copy = menu.addAction("📋  Sao chép đường dẫn")
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(str(tab_data.path)))

        menu.addSeparator()

        act_close = menu.addAction("✕  Đóng Tab này (Ctrl+W)")
        act_close.triggered.connect(lambda: self.close_tab(index))

        act_close_others = menu.addAction("🚫  Đóng các Tab khác")
        act_close_others.setEnabled(len(self.tabs) > 1)
        act_close_others.triggered.connect(lambda: self._close_other_tabs(index))

        menu.exec(global_pos)

    def _close_other_tabs(self, keep_index: int):
        if 0 <= keep_index < len(self.tabs):
            kept = self.tabs[keep_index]
            self.tabs = [kept]
            self.active_index = 0
            self._rebuild_tab_buttons()
            self.tab_switched.emit(0, kept.path)

"""
ui/widgets/toolbar.py
Custom application toolbar: Back/Forward/Up, interactive Breadcrumb Address Bar, Command Palette button, and search.
Rendered with crisp vector SVG icons and modern dark styling.
"""
from __future__ import annotations

from pathlib import Path
from collections import deque
from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSignal, QEvent, QSize
from PyQt6.QtGui     import QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QToolBar, QToolButton, QLineEdit, QWidget,
    QHBoxLayout, QSizePolicy, QLabel, QPushButton,
    QStackedWidget, QFrame,
)

from ui.widgets.svg_icons import get_svg_icon, get_svg_pixmap
from ui.theme import style, tok


class BreadcrumbPill(QPushButton):
    """Clickable segment pill for an ancestor directory in the breadcrumb bar."""
    def __init__(self, text: str, path: Path, is_drive: bool = False, parent=None):
        super().__init__(parent)
        self.path = path
        self.setText(f" {text}")
        icon_name = "drive" if is_drive else "folder"
        icon_color = tok("accent") if is_drive else tok("text_secondary")
        self.setIcon(get_svg_icon(icon_name, icon_color, 14))
        self.setIconSize(QSize(14, 14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)
        style(self, 
            "QPushButton { background-color: @fill_hover; color: @text_secondary; border: 1px solid @stroke_control; "
            "border-radius: 4px; padding: 2px 8px; font-size: 8.5pt; font-weight: 500; } "
            "QPushButton:hover { background-color: @fill_selected; color: @accent; border-color: @accent; }"
        )


class BreadcrumbAddressBar(QWidget):
    """
    Dual-mode Address Bar:
    - Mode 0 (Default): Interactive Breadcrumb pills: [ D: ] ❯ [ Folder ] ❯ [ Subfolder ]
    - Mode 1: Direct text input (QLineEdit) when clicked or triggered via Ctrl+L.
    """
    navigate_requested = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Optional[Path] = None

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.stack = QStackedWidget(self)

        # ── Page 0: Breadcrumb container ──
        self.crumb_widget = QFrame()
        self.crumb_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        style(self.crumb_widget, 
            "QFrame { background-color: @bg_layer; border: 1px solid @stroke_divider; "
            "border-radius: 6px; padding: 1px 4px; } "
            "QFrame:hover { border-color: @stroke_control; }"
        )
        self.crumb_layout = QHBoxLayout(self.crumb_widget)
        self.crumb_layout.setContentsMargins(4, 2, 4, 2)
        self.crumb_layout.setSpacing(4)
        self.crumb_widget.mousePressEvent = self._on_crumb_clicked

        self.stack.addWidget(self.crumb_widget)  # Index 0

        # ── Page 1: Raw line edit ──
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName("addressBar")
        self.line_edit.setPlaceholderText("Nhập đường dẫn...")
        self.line_edit.setFixedHeight(30)
        self.line_edit.returnPressed.connect(self._on_edit_return)
        self.line_edit.installEventFilter(self)

        self.stack.addWidget(self.line_edit)     # Index 1

        self.layout.addWidget(self.stack)
        self.setFixedHeight(32)

    def set_path(self, path: Path):
        self._current_path = path
        self.line_edit.setText(str(path))
        self._rebuild_breadcrumbs(path)
        self.stack.setCurrentIndex(0)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, text: str):
        self.line_edit.setText(text)
        try:
            p = Path(text)
            self.set_path(p)
        except Exception:
            pass

    def focus_edit(self):
        """Switch to raw line edit mode and focus."""
        self.stack.setCurrentIndex(1)
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def _on_crumb_clicked(self, event):
        self.focus_edit()

    def _on_edit_return(self):
        text = self.line_edit.text().strip()
        path = Path(text)
        if path.is_dir():
            self.set_path(path)
            self.navigate_requested.emit(path)
        else:
            style(self.line_edit, 
                "border: 1px solid @danger; background-color: @danger_bg;"
            )

    def eventFilter(self, obj, event):
        if obj == self.line_edit and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() == Qt.Key.Key_Escape:
                self.stack.setCurrentIndex(0)
                return True
        return super().eventFilter(obj, event)

    def _rebuild_breadcrumbs(self, path: Path):
        while self.crumb_layout.count():
            item = self.crumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        parts = path.parts
        if not parts:
            return

        accumulated = Path(parts[0])
        for idx, part in enumerate(parts):
            if idx > 0:
                accumulated = accumulated / part

            is_drive = (idx == 0 and ("\\" in part or "/" in part or ":" in part))
            lbl_text = part.rstrip('\\/') if is_drive else part

            pill = BreadcrumbPill(lbl_text, Path(accumulated), is_drive=is_drive)
            pill.clicked.connect(lambda checked, p=Path(accumulated): self.navigate_requested.emit(p))
            self.crumb_layout.addWidget(pill)

            if idx < len(parts) - 1:
                sep = QLabel("❯")
                style(sep, "color: @text_disabled; font-size: 7.5pt; font-weight: bold;")
                self.crumb_layout.addWidget(sep)

        self.crumb_layout.addStretch()

        # Edit button on far right
        btn_edit = QPushButton()
        btn_edit.setIcon(get_svg_icon("rename", tok("text_secondary"), 14, tok("accent")))
        btn_edit.setIconSize(QSize(14, 14))
        btn_edit.setToolTip("Nhập đường dẫn trực tiếp (Ctrl+L)")
        btn_edit.setFixedSize(22, 22)
        style(btn_edit, 
            "QPushButton { background: transparent; border: none; } "
            "QPushButton:hover { background: @fill_hover; border-radius: 4px; }"
        )
        btn_edit.clicked.connect(self.focus_edit)
        self.crumb_layout.addWidget(btn_edit)


class AppToolBar(QToolBar):
    navigate_requested = pyqtSignal(Path)
    search_requested   = pyqtSignal(str)
    palette_requested  = pyqtSignal()

    MAX_HISTORY = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setFloatable(False)
        self._history: deque[Path] = deque(maxlen=self.MAX_HISTORY)
        self._history_pos: int = -1
        self._build_actions()

    def _build_actions(self):
        # ── Back ──
        self.btn_back = QToolButton()
        self.btn_back.setIcon(get_svg_icon("arrow_left", tok("text_secondary"), 16, tok("accent")))
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setToolTip("Quay lại (Alt+Left)")
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self.go_back)
        self.addWidget(self.btn_back)

        # ── Forward ──
        self.btn_fwd = QToolButton()
        self.btn_fwd.setIcon(get_svg_icon("arrow_right", tok("text_secondary"), 16, tok("accent")))
        self.btn_fwd.setIconSize(QSize(16, 16))
        self.btn_fwd.setToolTip("Tiến lên (Alt+Right)")
        self.btn_fwd.setEnabled(False)
        self.btn_fwd.clicked.connect(self.go_forward)
        self.addWidget(self.btn_fwd)

        # ── Up ──
        self.btn_up = QToolButton()
        self.btn_up.setIcon(get_svg_icon("arrow_up", tok("text_secondary"), 16, tok("accent")))
        self.btn_up.setIconSize(QSize(16, 16))
        self.btn_up.setToolTip("Lên thư mục cha (Alt+Up)")
        self.btn_up.clicked.connect(self.go_up)
        self.addWidget(self.btn_up)

        self.addSeparator()

        # ── Interactive Breadcrumb Address bar ──
        self.address_bar = BreadcrumbAddressBar()
        self.address_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.address_bar.navigate_requested.connect(
            lambda p: (self.push_path(p), self.navigate_requested.emit(p))
        )
        self.addWidget(self.address_bar)

        self.addSeparator()

        # ── Command Palette Quick Launcher Button ──
        self.btn_palette = QToolButton()
        self.btn_palette.setIcon(get_svg_icon("command", tok("accent"), 16))
        self.btn_palette.setIconSize(QSize(16, 16))
        self.btn_palette.setToolTip("Mở Command Palette (Ctrl+K / Ctrl+P)")
        self.btn_palette.clicked.connect(self.palette_requested.emit)
        self.addWidget(self.btn_palette)

        # ── Search ──
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("Tìm kiếm (Ctrl+F)...")
        self.search_bar.setFixedWidth(200)
        self.search_bar.setFixedHeight(30)
        self.search_bar.textChanged.connect(
            lambda q: self.search_requested.emit(q)
        )
        self.addWidget(self.search_bar)

    # ─────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────

    def push_path(self, path: Path):
        """Record a navigation in history and update address bar."""
        if self._history_pos < len(self._history) - 1:
            hist_list = list(self._history)
            self._history = deque(hist_list[:self._history_pos + 1], maxlen=self.MAX_HISTORY)

        self._history.append(path)
        self._history_pos = len(self._history) - 1
        self.address_bar.set_path(path)
        self._update_nav_buttons()

    def go_back(self):
        if self._history_pos > 0:
            self._history_pos -= 1
            path = list(self._history)[self._history_pos]
            self.address_bar.set_path(path)
            self._update_nav_buttons()
            self.navigate_requested.emit(path)

    def go_forward(self):
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            path = list(self._history)[self._history_pos]
            self.address_bar.set_path(path)
            self._update_nav_buttons()
            self.navigate_requested.emit(path)

    def go_up(self):
        if self._history_pos >= 0:
            current = list(self._history)[self._history_pos]
            parent = current.parent
            if parent != current:
                self.push_path(parent)
                self.navigate_requested.emit(parent)

    def focus_address_bar(self):
        self.address_bar.focus_edit()

    def focus_search(self):
        self.search_bar.setFocus()

    def _update_nav_buttons(self):
        self.btn_back.setEnabled(self._history_pos > 0)
        self.btn_fwd.setEnabled(self._history_pos < len(self._history) - 1)

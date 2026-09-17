"""
ui/widgets/command_palette.py
Spotlight / Raycast-style Command Palette for FileManagerPro.
Provides instant keyboard-driven access to all commands, quick folder jumps, and settings (Ctrl+K / Ctrl+P).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QEvent
from PyQt6.QtGui import QKeyEvent, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QFrame,
    QGraphicsDropShadowEffect, QApplication, QSizePolicy,
)

from ui.widgets.svg_icons import get_svg_icon, get_svg_pixmap


@dataclass
class PaletteCommand:
    category: str        # e.g. "Hành động", "Điều hướng", "Giao diện"
    title: str           # e.g. "Đổi tên hàng loạt"
    icon_name: str       # e.g. "rename"
    shortcut: str = ""   # e.g. "Ctrl+R"
    callback: Optional[Callable[[], None]] = None
    path_target: Optional[Path] = None


class CommandItemWidget(QWidget):
    """Custom item row in the Command Palette list."""
    def __init__(self, cmd: PaletteCommand, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._build_ui()

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 14, 6)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Icon
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(22, 22)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setPixmap(get_svg_pixmap(self.cmd.icon_name, "#38bdf8", 18))
        lay.addWidget(self.lbl_icon)

        # Title
        self.lbl_title = QLabel(self.cmd.title)
        self.lbl_title.setStyleSheet("color: #f1f5f9; font-size: 10pt; font-weight: 500; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_title)

        # Category pill
        lbl_cat = QLabel(self.cmd.category)
        lbl_cat.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_cat.setStyleSheet(
            "color: #94a3b8; background-color: #1e293b; border-radius: 4px; "
            "padding: 2px 8px; font-size: 8pt; font-weight: 600;"
        )
        lay.addWidget(lbl_cat)

        # Shortcut pill (if any)
        if self.cmd.shortcut:
            lbl_key = QLabel(self.cmd.shortcut)
            lbl_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_key.setStyleSheet(
                "color: #cbd5e1; background-color: #0f172a; border: 1px solid #334155; "
                "border-radius: 4px; padding: 2px 8px; font-size: 8pt; font-family: 'Consolas', monospace;"
            )
            lay.addWidget(lbl_key)


class CommandPaletteDialog(QDialog):
    """
    Spotlight-style floating launcher triggered via Ctrl+K or Ctrl+P.
    """
    command_executed = pyqtSignal(object)  # Emits callback or navigates
    navigation_requested = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(680, 480)

        self._all_commands: list[PaletteCommand] = []
        self._filtered_commands: list[PaletteCommand] = []

        self._build_ui()

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(12, 12, 12, 12)

        self.container = QFrame(self)
        self.container.setObjectName("paletteContainer")
        self.container.setStyleSheet(
            "#paletteContainer { "
            "   background-color: #0e1526; "
            "   border: 1px solid #38bdf8; "
            "   border-radius: 12px; "
            "}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_lay = QVBoxLayout(self.container)
        container_lay.setContentsMargins(14, 14, 14, 12)
        container_lay.setSpacing(10)

        # ── Search Box Header ──
        search_bar = QHBoxLayout()
        search_bar.setSpacing(10)

        lbl_search_icon = QLabel()
        lbl_search_icon.setPixmap(get_svg_pixmap("search", "#38bdf8", 20))
        search_bar.addWidget(lbl_search_icon)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Gõ lệnh, tính năng hoặc đường dẫn cần mở (Ctrl+K)...")
        self.search_edit.setStyleSheet(
            "QLineEdit { "
            "   background: transparent; border: none; color: #f8fafc; "
            "   font-size: 11pt; font-weight: 500; selection-background-color: #0284c7; "
            "}"
        )
        self.search_edit.textChanged.connect(self._filter_commands)
        search_bar.addWidget(self.search_edit)

        lbl_esc = QLabel("Esc")
        lbl_esc.setStyleSheet(
            "color: #64748b; background-color: #1e293b; border-radius: 4px; "
            "padding: 2px 6px; font-size: 7.5pt; font-weight: bold;"
        )
        search_bar.addWidget(lbl_esc)

        container_lay.addLayout(search_bar)

        # Divider line
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: #1e293b;")
        container_lay.addWidget(div)

        # ── Results List ──
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(3)
        self.list_widget.setStyleSheet(
            "QListWidget { "
            "   background-color: transparent; border: none; outline: none; "
            "} "
            "QListWidget::item { "
            "   background-color: transparent; border-radius: 8px; margin: 1px 2px; "
            "   border: 1px solid transparent; "
            "} "
            "QListWidget::item:selected { "
            "   background-color: #1e293b; border: 1px solid #38bdf8; "
            "} "
            "QListWidget::item:hover:!selected { "
            "   background-color: #162032; border: 1px solid #1e293b; "
            "}"
        )
        self.list_widget.itemDoubleClicked.connect(self._execute_selected)
        container_lay.addWidget(self.list_widget, 1)

        # ── Footer ──
        footer = QHBoxLayout()
        self.lbl_count = QLabel("0 lệnh khả dụng")
        self.lbl_count.setStyleSheet("color: #64748b; font-size: 8pt;")
        footer.addWidget(self.lbl_count)

        footer.addStretch()

        lbl_hints = QLabel("[↑ / ↓] Điều hướng  •  [Enter] Thực thi  •  [Esc] Đóng")
        lbl_hints.setStyleSheet("color: #64748b; font-size: 8pt;")
        footer.addWidget(lbl_hints)

        container_lay.addLayout(footer)
        root_lay.addWidget(self.container)

    # ─────────────────────────────────────────────
    # Public Setup
    # ─────────────────────────────────────────────

    def set_commands(self, commands: list[PaletteCommand]):
        """Register the list of active commands."""
        self._all_commands = commands
        self._filter_commands(self.search_edit.text())

    def open_palette(self):
        """Show palette centered on top of parent/screen and focus search input."""
        self.search_edit.clear()
        self._filter_commands("")
        self._center_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_edit.setFocus()

    def _center_on_screen(self):
        parent = self.parentWidget()
        if parent:
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2 - 40
            self.move(max(10, x), max(10, y))
        else:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = (geo.width() - self.width()) // 2
                y = (geo.height() - self.height()) // 2 - 40
                self.move(x, y)

    # ─────────────────────────────────────────────
    # Filtering & Selection
    # ─────────────────────────────────────────────

    def _filter_commands(self, query: str):
        q = query.strip().lower()
        self.list_widget.clear()
        self._filtered_commands = []

        for cmd in self._all_commands:
            if not q or (q in cmd.title.lower() or q in cmd.category.lower() or q in cmd.shortcut.lower()):
                self._filtered_commands.append(cmd)

        for cmd in self._filtered_commands:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 48))
            row_widget = CommandItemWidget(cmd)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row_widget)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        self.lbl_count.setText(f"{len(self._filtered_commands)} kết quả")

    def _execute_selected(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._filtered_commands):
            cmd = self._filtered_commands[row]
            self.close()
            if cmd.path_target:
                self.navigation_requested.emit(cmd.path_target)
            elif cmd.callback:
                cmd.callback()

    # ─────────────────────────────────────────────
    # Keyboard Event Navigation
    # ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._execute_selected()
            event.accept()
        elif key == Qt.Key.Key_Down:
            cur = self.list_widget.currentRow()
            if cur < self.list_widget.count() - 1:
                self.list_widget.setCurrentRow(cur + 1)
            event.accept()
        elif key == Qt.Key.Key_Up:
            cur = self.list_widget.currentRow()
            if cur > 0:
                self.list_widget.setCurrentRow(cur - 1)
            event.accept()
        else:
            super().keyPressEvent(event)

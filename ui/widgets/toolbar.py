"""
ui/widgets/toolbar.py
Explorer address row: Back / Forward / Up / Refresh, the breadcrumb address box and
the search box.

Address box (as in Windows 11 Explorer):
  [icon] This PC > Local Disk (C:) > Users > huunh > Pictures >
- each segment navigates; each '>' opens a menu of that folder's subfolders;
- leading segments collapse into a '«' menu when the path does not fit;
- clicking empty space (or Ctrl+L) switches to a text box with the full path.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QSizePolicy, QStackedWidget,
    QToolBar, QToolButton, QWidget,
)

from ui.shell import (
    GLYPH_BACK, GLYPH_CHEVRON_RIGHT, GLYPH_FORWARD, GLYPH_REFRESH,
    GLYPH_SEARCH, GLYPH_UP, computer_icon, drive_display_name, glyph_font, is_drive_root,
    list_drives, shell_icon, subfolders,
)
from ui.theme import style

ROW_CONTROL_HEIGHT = 26   # Explorer address/search box: 32 physical px at 125%
THIS_PC = "This PC"

_FLAT_BUTTON_QSS = (
    "QToolButton { background: transparent; border: none; border-radius: 4px; "
    "color: @text_primary; padding: 0px 6px; }"
    "QToolButton:hover { background: @hover_on_mica; }"
    "QToolButton:pressed { background: @layer_on_mica; color: @text_secondary; }"
    "QToolButton:disabled { color: @text_disabled; }"
    "QToolButton::menu-indicator { image: none; width: 0px; }"
)


def _flat_button(text: str = "", glyph_px: int = 0, tooltip: str = "") -> QToolButton:
    b = QToolButton()
    b.setText(text)
    if glyph_px:
        b.setFont(glyph_font(glyph_px))
    b.setToolTip(tooltip)
    b.setAccessibleName(text or tooltip.split(" (")[0])     # names for icon-only and crumb buttons
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    style(b, _FLAT_BUTTON_QSS)
    return b


class BreadcrumbAddressBar(QWidget):
    """Breadcrumb address box with a text-edit mode (see module docstring)."""

    navigate_requested = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Optional[Path] = None
        self._segments: list[tuple[QToolButton, QToolButton]] = []   # (crumb, chevron)
        self.setFixedHeight(ROW_CONTROL_HEIGHT)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        # ── Page 0: breadcrumbs ──
        self.crumb_box = QFrame()
        self.crumb_box.setObjectName("addressBox")
        self.crumb_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        style(self.crumb_box,
              "#addressBox { background: @control_on_mica; border: 1px solid transparent; border-radius: 4px; }"
              "#addressBox:hover { border-color: @stroke_control; }")
        self.crumb_box.mousePressEvent = lambda e: self.focus_edit()
        row = QHBoxLayout(self.crumb_box)
        row.setContentsMargins(8, 0, 2, 0)
        row.setSpacing(0)

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(16, 16)
        row.addWidget(self.lbl_icon)
        row.addSpacing(6)

        self.btn_overflow = _flat_button("«", tooltip="Các thư mục cha")
        self.btn_overflow.setFixedHeight(ROW_CONTROL_HEIGHT - 6)
        self.btn_overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_overflow.hide()
        row.addWidget(self.btn_overflow)

        self.crumbs_host = QWidget()
        self.crumbs_layout = QHBoxLayout(self.crumbs_host)
        self.crumbs_layout.setContentsMargins(0, 0, 0, 0)
        self.crumbs_layout.setSpacing(0)
        self.crumb_layout = self.crumbs_layout     # name used by older callers/tests
        row.addWidget(self.crumbs_host)
        row.addStretch(1)
        self.stack.addWidget(self.crumb_box)

        # ── Page 1: text edit ──
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName("addressBar")
        self.line_edit.setPlaceholderText("Nhập đường dẫn...")
        self.line_edit.setFixedHeight(ROW_CONTROL_HEIGHT)
        self.line_edit.returnPressed.connect(self._on_edit_return)
        self.line_edit.installEventFilter(self)
        self.stack.addWidget(self.line_edit)

    # ── public API (kept from the previous address bar) ──

    def set_path(self, path: Path):
        self._current_path = path
        self.line_edit.setText(str(path))
        self.line_edit.setProperty("invalid", False)
        self._rebuild_breadcrumbs(path)
        self.stack.setCurrentIndex(0)

    def set_location(self, label: str, icon: QIcon):
        """A page that is not a folder (like Explorer's Home / Gallery): icon > label."""
        self._current_path = None
        self.line_edit.setText(label)
        self.line_edit.setProperty("invalid", False)
        self._clear_crumbs()
        self.lbl_icon.setPixmap(icon.pixmap(16, 16))
        crumb = _flat_button(label)
        crumb.setFixedHeight(ROW_CONTROL_HEIGHT - 6)
        chevron = _flat_button(GLYPH_CHEVRON_RIGHT, 8)
        chevron.setFixedSize(18, ROW_CONTROL_HEIGHT - 6)
        chevron.setEnabled(False)
        self.crumbs_layout.addWidget(crumb)
        self.crumbs_layout.addWidget(chevron)
        self._segments.append((crumb, chevron))
        self.stack.setCurrentIndex(0)
        self._fit_crumbs()

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, text: str):
        self.line_edit.setText(text)
        try:
            self.set_path(Path(text))
        except Exception:
            pass

    def focus_edit(self):
        """Switch to the text box with the full path selected (Ctrl+L / click on empty space)."""
        self.stack.setCurrentIndex(1)
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def crumb_texts(self) -> list[str]:
        return [c.text() for c, _ in self._segments]

    # ── breadcrumbs ──

    def _segments_for(self, path: Path) -> list[tuple[str, Optional[Path]]]:
        """[(label, path)] from 'This PC' down to `path`; 'This PC' has no folder path."""
        parts = path.parts
        if not parts:
            return [(THIS_PC, None)]
        segs: list[tuple[str, Optional[Path]]] = [(THIS_PC, None)]
        acc = Path(parts[0])
        segs.append((drive_display_name(acc) if is_drive_root(acc) else parts[0].rstrip("\\/"), acc))
        for part in parts[1:]:
            acc = acc / part
            segs.append((part, acc))
        return segs

    def _clear_crumbs(self):
        while self.crumbs_layout.count():
            item = self.crumbs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._segments.clear()

    def _rebuild_breadcrumbs(self, path: Path):
        self._clear_crumbs()

        # Explorer shows the icon of the location root: "This PC" for drive paths
        icon = computer_icon() if path.drive else shell_icon(path)
        self.lbl_icon.setPixmap(icon.pixmap(16, 16))
        for label, seg_path in self._segments_for(path):
            crumb = _flat_button(label)
            crumb.setFixedHeight(ROW_CONTROL_HEIGHT - 6)
            if seg_path is None:   # "This PC": no folder view yet, so it lists the drives
                crumb.clicked.connect(lambda _=False, b=crumb: self._show_drives_menu(b))
            else:
                crumb.clicked.connect(lambda _=False, p=seg_path: self.navigate_requested.emit(p))
            chevron = _flat_button(GLYPH_CHEVRON_RIGHT, 8)
            chevron.setFixedSize(18, ROW_CONTROL_HEIGHT - 6)
            chevron.setToolTip("Thư mục con")
            if seg_path is None:
                chevron.clicked.connect(lambda _=False, b=chevron: self._show_drives_menu(b))
            else:
                chevron.clicked.connect(lambda _=False, p=seg_path, b=chevron: self._show_children_menu(p, b))
            self.crumbs_layout.addWidget(crumb)
            self.crumbs_layout.addWidget(chevron)
            self._segments.append((crumb, chevron))
        self._fit_crumbs()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_crumbs()

    def _fit_crumbs(self):
        """Collapse leading segments into the '«' menu until the rest fits."""
        if not self._segments:
            return
        for crumb, chevron in self._segments:
            crumb.show(); chevron.show()
        reserved = 16 + 6 + 16                                    # icon, gap, padding
        available = max(0, self.crumb_box.width() - reserved)

        def width_of(i):
            c, ch = self._segments[i]
            return c.sizeHint().width() + ch.width()

        total = sum(width_of(i) for i in range(len(self._segments)))
        hidden = 0
        overflow_w = self.btn_overflow.sizeHint().width()
        while total + (overflow_w if hidden else 0) > available and hidden < len(self._segments) - 1:
            total -= width_of(hidden)
            c, ch = self._segments[hidden]
            c.hide(); ch.hide()
            hidden += 1

        if hidden:
            menu = QMenu(self.btn_overflow)
            for crumb, _ in self._segments[:hidden][::-1]:
                act = menu.addAction(crumb.text())
                act.triggered.connect(crumb.click)
            self.btn_overflow.setMenu(menu)
        self.btn_overflow.setVisible(bool(hidden))

    def hidden_crumb_count(self) -> int:
        return sum(1 for c, _ in self._segments if c.isHidden())

    # ── menus ──

    def _popup(self, menu: QMenu, anchor: QWidget):
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _children_menu(self, folder: Path) -> QMenu:
        menu = QMenu(self)
        # Listing runs on the UI thread; a slow network folder at least shows a busy cursor
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            children = subfolders(folder)
        finally:
            QApplication.restoreOverrideCursor()
        if not children:
            act = menu.addAction("(Không có thư mục con)")
            act.setEnabled(False)
        for child in children:
            act = menu.addAction(shell_icon(child), child.name)
            act.triggered.connect(lambda _=False, p=child: self.navigate_requested.emit(p))
        return menu

    def _show_children_menu(self, folder: Path, anchor: QWidget):
        self._popup(self._children_menu(folder), anchor)

    def _drives_menu(self) -> QMenu:
        menu = QMenu(self)
        for root in list_drives():
            act = menu.addAction(shell_icon(root), drive_display_name(root))
            act.triggered.connect(lambda _=False, p=root: self.navigate_requested.emit(p))
        return menu

    def _show_drives_menu(self, anchor: QWidget):
        self._popup(self._drives_menu(), anchor)

    # ── text edit mode ──

    def _on_edit_return(self):
        path = Path(self.line_edit.text().strip().strip('"'))
        if path.is_dir():
            self.set_path(path)
            self.navigate_requested.emit(path)
        else:
            self.line_edit.setProperty("invalid", True)
            self.line_edit.style().unpolish(self.line_edit)
            self.line_edit.style().polish(self.line_edit)

    def eventFilter(self, obj, event):
        if obj is self.line_edit:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._leave_edit()
                return True
            if event.type() == QEvent.Type.FocusOut and self.stack.currentIndex() == 1:
                self._leave_edit()
        return super().eventFilter(obj, event)

    def _leave_edit(self):
        if self._current_path is not None:
            self.line_edit.setText(str(self._current_path))
        self.line_edit.setProperty("invalid", False)
        self.stack.setCurrentIndex(0)


class SearchBox(QFrame):
    """Explorer search box: 'Search <folder>' placeholder, magnifier on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(ROW_CONTROL_HEIGHT)
        style(self,
              "#searchBox { background: @control_on_mica; border: 1px solid transparent; border-radius: 4px; }"
              "#searchBox:hover { border-color: @stroke_control; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setObjectName("searchBar")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        icon = QLabel(GLYPH_SEARCH)
        icon.setFont(glyph_font(12))
        style(icon, "background: transparent; color: @text_secondary;")
        lay.addWidget(icon)

    def set_folder(self, path: Path):
        name = drive_display_name(path) if is_drive_root(path) else path.name
        self.edit.setPlaceholderText(f"Tìm trong {name}")


class AppToolBar(QToolBar):
    navigate_requested = pyqtSignal(Path)
    search_requested   = pyqtSignal(str)
    palette_requested  = pyqtSignal()        # kept for the command palette entry point
    refresh_requested  = pyqtSignal()

    MAX_HISTORY = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setFloatable(False)
        self._history: deque[Path] = deque(maxlen=self.MAX_HISTORY)
        self._history_pos: int = -1
        self.page_label: Optional[str] = None   # set while a non-folder page is shown
        self._build_actions()

    def _build_actions(self):
        def nav(glyph: str, tip: str, slot) -> QToolButton:
            b = _flat_button(glyph, 12, tip)
            b.setFixedSize(34, ROW_CONTROL_HEIGHT)        # + 4px toolbar spacing = Explorer's 38
            b.clicked.connect(slot)
            self.addWidget(b)
            return b

        self.btn_back = nav(GLYPH_BACK, "Quay lại (Alt+Left)", self.go_back)
        self.btn_fwd = nav(GLYPH_FORWARD, "Tiến lên (Alt+Right)", self.go_forward)
        self.btn_up = nav(GLYPH_UP, "Lên thư mục cha (Alt+Up)", self.go_up)
        self.btn_refresh = nav(GLYPH_REFRESH, "Làm mới (F5)", self.refresh_requested.emit)
        self.btn_back.setEnabled(False)
        self.btn_fwd.setEnabled(False)

        spacer = QWidget(); spacer.setFixedWidth(8)
        self.addWidget(spacer)

        self.address_bar = BreadcrumbAddressBar()
        self.address_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.address_bar.navigate_requested.connect(
            lambda p: (self.push_path(p), self.navigate_requested.emit(p))
        )
        self.addWidget(self.address_bar)

        spacer2 = QWidget(); spacer2.setFixedWidth(8)
        self.addWidget(spacer2)

        self.search_box = SearchBox()
        self.search_box.setFixedWidth(274)
        self.search_bar = self.search_box.edit      # kept for focus_search / callers
        self.search_bar.textChanged.connect(lambda q: self.search_requested.emit(q))
        self.addWidget(self.search_box)

    # ─────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────

    def push_path(self, path: Path):
        """Record a navigation in history and update address bar."""
        if self._history_pos >= 0 and list(self._history)[self._history_pos] == path:
            # Back / Forward / a refresh land here too: the entry is already current, and
            # appending it again would cut off the Forward history
            self._show_path(path)
            return
        if self._history_pos < len(self._history) - 1:
            hist_list = list(self._history)
            self._history = deque(hist_list[:self._history_pos + 1], maxlen=self.MAX_HISTORY)

        self._history.append(path)
        self._history_pos = len(self._history) - 1
        self._show_path(path)

    def show_location(self, label: str, icon: QIcon):
        """Show a page (duplicates / inspector) in the address row; Back / Up return to the folder."""
        self.page_label = label
        self.address_bar.set_location(label, icon)
        self.search_box.edit.setPlaceholderText(f"Tìm trong {label}")
        self.search_box.setEnabled(False)
        has_folder = self._history_pos >= 0
        self.btn_back.setEnabled(has_folder)
        self.btn_up.setEnabled(has_folder)

    def leave_page(self, emit: bool = False) -> bool:
        """Show the current folder again instead of a page (not a history step).
        emit: also ask the window to navigate there (Back / Up pressed on a page)."""
        if self.page_label is None or self._history_pos < 0:
            return False
        path = list(self._history)[self._history_pos]
        self._show_path(path)
        if emit:
            self.navigate_requested.emit(path)
        return True

    def go_back(self):
        if self.leave_page(emit=True):
            return
        if self._history_pos > 0:
            self._history_pos -= 1
            path = list(self._history)[self._history_pos]
            self._show_path(path)
            self.navigate_requested.emit(path)

    def go_forward(self):
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            path = list(self._history)[self._history_pos]
            self._show_path(path)
            self.navigate_requested.emit(path)

    def go_up(self):
        if self.leave_page(emit=True):
            return
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
        self.search_bar.selectAll()

    def _show_path(self, path: Path):
        self.page_label = None
        self.address_bar.set_path(path)
        self.search_box.set_folder(path)
        self.search_box.setEnabled(True)
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        self.btn_back.setEnabled(self._history_pos > 0)
        self.btn_fwd.setEnabled(self._history_pos < len(self._history) - 1)
        current = list(self._history)[self._history_pos] if self._history_pos >= 0 else None
        self.btn_up.setEnabled(current is not None and current.parent != current)

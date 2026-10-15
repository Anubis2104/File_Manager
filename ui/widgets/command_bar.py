"""
ui/widgets/command_bar.py
Explorer command bar:

  (+) Mới v | Cắt  Sao chép  Dán  Đổi tên  Xóa | Sắp xếp v  Xem v | Công cụ v  ...      [] Chi tiết

The app's own tools (batch rename, duplicates, inspector, metadata...) live in the
"Công cụ" menu and the "..." menu, the way Explorer keeps extra verbs behind "...".
Explorer's Share button is intentionally absent: it needs the WinRT share sheet.
"""
from __future__ import annotations

from typing import Optional, Sequence

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QToolBar, QToolButton, QWidget, QSizePolicy

from ui.shell import glyph_font
from ui.theme import qcolor, style, theme

GLYPH = {
    "new": "", "cut": "", "copy": "", "paste": "",
    "rename": "", "delete": "", "sort": "", "view": "",
    "tools": "", "more": "", "details": "",
}

# QFileSystemModel columns
COL_NAME, COL_SIZE, COL_TYPE, COL_DATE = 0, 1, 2, 3


def glyph_icon(glyph: str, px: int = 16) -> QIcon:
    """Theme-colored icon from a Segoe Fluent glyph, with a proper disabled state."""
    icon = QIcon()
    for mode, token in ((QIcon.Mode.Normal, "text_primary"), (QIcon.Mode.Active, "text_primary"),
                        (QIcon.Mode.Disabled, "text_disabled")):
        for scale in (1, 2):                       # crisp on 100-200% displays
            pm = QPixmap(px * scale, px * scale)
            pm.setDevicePixelRatio(scale)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.setFont(glyph_font(px))
            p.setPen(qcolor(token))
            p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, glyph)
            p.end()
            icon.addPixmap(pm, mode)
    return icon


_BUTTON_QSS = (
    "QToolButton { background: transparent; border: none; border-radius: 4px; "
    "color: @text_primary; padding: 4px 8px; }"
    "QToolButton:hover { background: @fill_hover; }"
    "QToolButton:pressed, QToolButton:checked { background: @fill_pressed; }"
    "QToolButton:disabled { color: @text_disabled; }"
    "QToolButton::menu-indicator { image: url(@chevron_down); subcontrol-position: right center; "
    "subcontrol-origin: padding; width: 10px; height: 10px; right: 4px; }"
)


class CommandBar(QToolBar):
    new_folder_requested = pyqtSignal()
    cut_requested = pyqtSignal()
    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    rename_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    sort_requested = pyqtSignal(int, object)      # (column, Qt.SortOrder)
    view_requested = pyqtSignal(str)              # "grid" | "detail"
    details_toggled = pyqtSignal(bool)

    def __init__(self, tools_actions: Sequence[Optional[QAction]] = (),
                 more_actions: Sequence[Optional[QAction]] = (), parent=None):
        super().__init__("Command bar", parent)
        self.setObjectName("commandBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(16, 16))
        self._glyph_buttons: list[tuple[QToolButton, str]] = []

        # New ▾
        new_menu = QMenu(self)
        self.act_new_folder = new_menu.addAction("Thư mục")
        self.act_new_folder.setShortcutVisibleInContextMenu(True)
        self.act_new_folder.setShortcut("Ctrl+Shift+N")
        # Shown in the menu only: MainWindow owns the real shortcut, and two registrations
        # of one key make Qt treat it as ambiguous and fire neither.
        self.act_new_folder.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_new_folder.triggered.connect(self.new_folder_requested.emit)
        self.btn_new = self._button("new", "Mới", "Tạo mục mới", menu=new_menu)
        self.addSeparator()

        # Clipboard / item verbs (icon only, as in Explorer)
        self.btn_cut = self._button("cut", "", "Cắt (Ctrl+X)", self.cut_requested)
        self.btn_copy = self._button("copy", "", "Sao chép (Ctrl+C)", self.copy_requested)
        self.btn_paste = self._button("paste", "", "Dán (Ctrl+V)", self.paste_requested)
        self.btn_rename = self._button("rename", "", "Đổi tên (F2)", self.rename_requested)
        self.btn_delete = self._button("delete", "", "Xóa vào Thùng rác (Delete)", self.delete_requested)
        self.addSeparator()

        # Sort ▾
        self.sort_menu = QMenu(self)
        self._sort_column, self._sort_order = COL_NAME, Qt.SortOrder.AscendingOrder
        col_group = QActionGroup(self)
        self._sort_column_actions = {}
        for label, col in (("Tên", COL_NAME), ("Ngày sửa đổi", COL_DATE), ("Loại", COL_TYPE), ("Kích thước", COL_SIZE)):
            act = self.sort_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(col == COL_NAME)
            col_group.addAction(act)
            act.triggered.connect(lambda _=False, c=col: self._set_sort(column=c))
            self._sort_column_actions[col] = act
        self.sort_menu.addSeparator()
        order_group = QActionGroup(self)
        self.act_ascending = self.sort_menu.addAction("Tăng dần")
        self.act_descending = self.sort_menu.addAction("Giảm dần")
        for act, order in ((self.act_ascending, Qt.SortOrder.AscendingOrder),
                           (self.act_descending, Qt.SortOrder.DescendingOrder)):
            act.setCheckable(True)
            order_group.addAction(act)
            act.triggered.connect(lambda _=False, o=order: self._set_sort(order=o))
        self.act_ascending.setChecked(True)
        self.btn_sort = self._button("sort", "Sắp xếp", "Sắp xếp các mục", menu=self.sort_menu)

        # View ▾ — Explorer's eight layouts, with its Ctrl+Shift+1..8 shortcuts shown
        from ui.panels.explorer_delegate import VIEW_ORDER, VIEW_SPECS
        self.view_menu = QMenu(self)
        view_group = QActionGroup(self)
        self.view_actions: dict[str, QAction] = {}
        for n, mode in enumerate(VIEW_ORDER, start=1):
            act = self.view_menu.addAction(VIEW_SPECS[mode].label)
            act.setCheckable(True)
            act.setShortcut(f"Ctrl+Shift+{n}")
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)   # display only (see New)
            act.setShortcutVisibleInContextMenu(True)
            view_group.addAction(act)
            act.triggered.connect(lambda _=False, m=mode: self.view_requested.emit(m))
            self.view_actions[mode] = act
        self.act_view_grid = self.view_actions["large"]       # names used by older callers
        self.act_view_detail = self.view_actions["detail"]
        self.act_view_detail.setChecked(True)
        self.view_menu.addSeparator()
        self.act_details_pane = self.view_menu.addAction("Khung chi tiết")
        self.act_details_pane.setCheckable(True)
        self.act_details_pane.setChecked(True)
        self.act_details_pane.toggled.connect(self._on_details_toggled)
        self.btn_view = self._button("view", "Xem", "Chế độ xem", menu=self.view_menu)
        self.addSeparator()

        # App tools ▾ and "..."
        self.tools_menu = self._menu_from(tools_actions)
        self.btn_tools = self._button("tools", "Công cụ", "Công cụ của FileManagerPro", menu=self.tools_menu)
        self.more_menu = self._menu_from(more_actions)
        self.btn_more = self._button("more", "", "Xem thêm", menu=self.more_menu)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        # Details pane toggle (right edge, like Explorer)
        self.btn_details = self._button("details", "Chi tiết", "Hiện/ẩn khung chi tiết")
        self.btn_details.setCheckable(True)
        self.btn_details.setChecked(True)
        self.btn_details.toggled.connect(self._on_details_toggled)

        theme().changed.connect(self._refresh_icons)   # bound method: auto-disconnects on destroy
        self.update_state(selection_count=0, can_paste=False)

    # ── construction helpers ──

    def _button(self, glyph: str, text: str, tooltip: str, signal=None, menu: Optional[QMenu] = None) -> QToolButton:
        b = QToolButton(self)
        b.setIcon(glyph_icon(GLYPH[glyph]))
        b.setText(f" {text}" if text else "")        # Explorer leaves a small gap after the icon
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text
                             else Qt.ToolButtonStyle.ToolButtonIconOnly)
        b.setToolTip(tooltip)
        b.setAutoRaise(True)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if signal is not None:
            b.clicked.connect(signal.emit)
        # Text buttons with a menu show a chevron (Sort v, View v); "..." does not, like Explorer
        if menu is not None and text:
            extra = "QToolButton { padding-right: 18px; }"
        elif menu is not None:
            extra = "QToolButton::menu-indicator { image: none; width: 0px; }"
        else:
            extra = ""
        style(b, _BUTTON_QSS + extra)
        self.addWidget(b)
        self._glyph_buttons.append((b, glyph))
        return b

    def _menu_from(self, actions: Sequence[Optional[QAction]]) -> QMenu:
        menu = QMenu(self)
        for act in actions:
            if act is None:
                menu.addSeparator()
            else:
                menu.addAction(act)
        return menu

    def _refresh_icons(self, _tokens=None):
        for b, glyph in self._glyph_buttons:
            b.setIcon(glyph_icon(GLYPH[glyph]))

    # ── state ──

    def update_state(self, selection_count: int, can_paste: bool) -> None:
        has_sel = selection_count > 0
        for b in (self.btn_cut, self.btn_copy, self.btn_delete):
            b.setEnabled(has_sel)
        self.btn_rename.setEnabled(has_sel)
        self.btn_rename.setToolTip("Đổi tên (F2)" if selection_count <= 1 else "Đổi tên hàng loạt (F2)")
        self.btn_paste.setEnabled(can_paste)

    def set_view_mode(self, mode: str) -> None:
        act = self.view_actions.get("large" if mode == "grid" else mode)
        if act is not None:
            act.setChecked(True)

    def _set_sort(self, column: Optional[int] = None, order=None) -> None:
        if column is not None:
            self._sort_column = column
        if order is not None:
            self._sort_order = order
        self.sort_requested.emit(self._sort_column, self._sort_order)

    def _on_details_toggled(self, on: bool) -> None:
        # Keep the toolbar button and the View-menu entry in sync, emit once
        for w in (self.btn_details, self.act_details_pane):
            if w.isChecked() != on:
                w.blockSignals(True); w.setChecked(on); w.blockSignals(False)
        self.details_toggled.emit(on)

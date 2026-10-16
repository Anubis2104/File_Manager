"""
ui/panels/explorer_delegate.py
Item painting for Explorer's icon / list / tiles / content views (the Details view is a
table and uses the default painting with ExplorerFileSystemModel's columns).

Images come from the Windows Shell via ui.thumbnails (thumbnails for photos/videos/PDFs,
folder previews, file-type icons); until a thumbnail arrives the model's icon is shown.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter, QPainterPath, QPixmap, QTextLayout, QTextOption
from PyQt6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.explorer_model import COL_SIZE, COL_TYPE
from ui.theme import qcolor
from ui.thumbnails import ThumbnailCache


@dataclass(frozen=True)
class ViewSpec:
    key: str
    label: str
    kind: str              # "icon" | "row" | "tile" | "content"
    icon: int              # logical icon size
    cell: Optional[QSize]  # grid cell (None = full-width rows)
    flow_down: bool = False


# Explorer's eight layouts, in its View-menu order (Ctrl+Shift+1..8)
VIEW_SPECS: dict[str, ViewSpec] = {s.key: s for s in (
    ViewSpec("xl", "Biểu tượng rất lớn", "icon", 256, QSize(272, 300)),
    ViewSpec("large", "Biểu tượng lớn", "icon", 96, QSize(116, 150)),
    ViewSpec("medium", "Biểu tượng vừa", "icon", 48, QSize(88, 96)),
    ViewSpec("small", "Biểu tượng nhỏ", "row", 16, QSize(220, 24)),
    ViewSpec("list", "Danh sách", "row", 16, QSize(220, 24), flow_down=True),
    ViewSpec("detail", "Chi tiết", "table", 16, None),
    ViewSpec("tiles", "Ô xếp", "tile", 48, QSize(264, 62)),
    ViewSpec("content", "Nội dung", "content", 32, None),
)}
VIEW_ORDER = list(VIEW_SPECS)


def wrap_lines(text: str, font, width: int, max_lines: int) -> list[str]:
    """Word-wrap `text` into at most `max_lines`, eliding the last line like Explorer."""
    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    lines: list[str] = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        lines.append(text[line.textStart(): line.textStart() + line.textLength()])
    layout.endLayout()
    if len(lines) <= max_lines:
        return [l.rstrip() for l in lines]
    head = [l.rstrip() for l in lines[:max_lines - 1]]
    rest = "".join(lines[max_lines - 1:])
    return head + [QFontMetrics(font).elidedText(rest, Qt.TextElideMode.ElideRight, width)]


class ExplorerItemDelegate(QStyledItemDelegate):
    def __init__(self, view: QListView, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.spec = VIEW_SPECS["large"]
        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.setInterval(30)                    # coalesce bursts of thumbnails
        self._repaint.timeout.connect(lambda: self.view.viewport().update())
        ThumbnailCache.instance().ready.connect(self._on_thumbnail_ready)

    def set_spec(self, spec: ViewSpec):
        self.spec = spec

    def _on_thumbnail_ready(self, _path: str, _size: int):
        if self.view.isVisible():
            self._repaint.start()

    # ── geometry ──

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if self.spec.cell is not None:
            return self.spec.cell
        return QSize(max(200, self.view.viewport().width() - 12), 56 if self.spec.kind == "content" else 24)

    # ── painting ──

    def _image(self, index: QModelIndex, px: int) -> QPixmap:
        model = index.model()
        if px > 16:
            dpr = self.view.devicePixelRatioF() or 1.0
            pm = ThumbnailCache.instance().get(model.filePath(index), int(round(px * dpr)))
            if pm is not None:
                return pm
        return model.fileIcon(index).pixmap(QSize(px, px))

    def _draw_image(self, painter: QPainter, area: QRect, pm: QPixmap):
        if pm.isNull():
            return
        dpr = pm.devicePixelRatioF() or 1.0
        size = QSize(int(pm.width() / dpr), int(pm.height() / dpr)).scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(area.center())
        if self.spec.kind == "icon":
            target.moveBottom(area.bottom())            # photos sit on a common baseline, like Explorer
        painter.drawPixmap(target, pm)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(QRectF(r), 4, 4)
            painter.fillPath(path, qcolor("fill_selected" if selected else "fill_hover"))

        model = index.model()
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        font = option.font
        fm = QFontMetrics(font)
        kind, px = self.spec.kind, self.spec.icon
        primary, secondary = qcolor("text_primary"), qcolor("text_secondary")

        if kind == "icon":
            icon_area = QRect(r.left() + 4, r.top() + 4, r.width() - 8, px)
            self._draw_image(painter, icon_area, self._image(index, px))
            text_top = icon_area.bottom() + 6
            width = r.width() - 8
            painter.setPen(primary)
            for i, line in enumerate(wrap_lines(name, font, width, 2)):
                painter.drawText(QRect(r.left() + 4, text_top + i * fm.height(), width, fm.height()),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
        else:
            icon_area = QRect(r.left() + 6, r.top() + (r.height() - px) // 2, px, px)
            self._draw_image(painter, icon_area, self._image(index, px))
            x = icon_area.right() + 8
            width = r.right() - x - 6
            if kind == "row":
                painter.setPen(primary)
                painter.drawText(QRect(x, r.top(), width, r.height()), Qt.AlignmentFlag.AlignVCenter,
                                 fm.elidedText(name, Qt.TextElideMode.ElideRight, width))
            else:
                type_text = model.index(index.row(), COL_TYPE, index.parent()).data() or ""
                size_text = model.index(index.row(), COL_SIZE, index.parent()).data() or ""
                lines = [(name, primary), (type_text, secondary)]
                if kind == "tile" and size_text:
                    lines.append((size_text, secondary))
                if kind == "content":                    # metadata column on the right, like Explorer
                    meta_w = min(220, width // 3)
                    width -= meta_w
                    date_text = model.lastModified(index).toString("dd/MM/yyyy HH:mm")
                    painter.setPen(secondary)
                    painter.drawText(QRect(r.right() - meta_w - 6, r.top() + 6, meta_w, fm.height()),
                                     Qt.AlignmentFlag.AlignRight, date_text)
                    if size_text:
                        painter.drawText(QRect(r.right() - meta_w - 6, r.top() + 6 + fm.height(), meta_w, fm.height()),
                                         Qt.AlignmentFlag.AlignRight, size_text)
                top = r.top() + (r.height() - fm.height() * len(lines)) // 2
                for i, (text, color) in enumerate(lines):
                    painter.setPen(color)
                    painter.drawText(QRect(x, top + i * fm.height(), width, fm.height()), Qt.AlignmentFlag.AlignVCenter,
                                     fm.elidedText(text, Qt.TextElideMode.ElideRight, width))
        painter.restore()

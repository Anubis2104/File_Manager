"""
ui/panels/media_card_delegate.py
Custom QStyledItemDelegate for QListView grid view in ContentPanel.
Renders files as sleek, rounded media cards with category badges, format pills, and clean typography.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QSize, QModelIndex
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPixmap,
    QFontMetrics, QFileSystemModel, QImageReader,
)
from PyQt6.QtWidgets import (
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)

from ui.widgets.svg_icons import get_svg_pixmap
from utils.file_utils import IMAGE_EXTS, VIDEO_EXTS, RAW_EXTS
from ui.theme import qcolor, tok


class MediaCardDelegate(QStyledItemDelegate):
    """
    Renders files as modern cards in QListView:
    ┌─────────────────────────┐
    │  [Thumbnail / Icon]     │ [Badge]
    │                         │
    │  Filename.jpg           │
    │  2.4 MB                 │
    └─────────────────────────┘
    """
    CARD_WIDTH = 114
    CARD_HEIGHT = 124
    THUMB_HEIGHT = 74

    def __init__(self, model: QFileSystemModel, parent=None):
        super().__init__(parent)
        self.model = model
        self._thumb_cache: dict[Path, QPixmap] = {}
        self._max_cache_size = 250

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(self.CARD_WIDTH, self.CARD_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        file_path_str = self.model.filePath(index)
        path = Path(file_path_str)
        is_dir = self.model.isDir(index)

        # Card rect
        rect = option.rect.adjusted(3, 3, -3, -3)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ── 1. Draw Card Background & Border ──
        if is_selected:
            bg_color = qcolor("fill_selected")   # Explorer: neutral selection fill, accent outline
            border_color = qcolor("accent")
            border_width = 1.5
        elif is_hover:
            bg_color = qcolor("fill_hover")
            border_color = qcolor("fill_selected")
            border_width = 1.0
        else:
            bg_color = qcolor("bg_layer")
            border_color = qcolor("fill_hover")
            border_width = 1.0

        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, border_width))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        # ── 2. Draw Thumbnail / Icon Area ──
        thumb_area = QRect(rect.x() + 6, rect.y() + 6, rect.width() - 12, self.THUMB_HEIGHT)

        # Inner thumbnail backdrop
        painter.setBrush(QBrush(qcolor("bg_base")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(thumb_area, 6.0, 6.0)

        badge_text = ""
        badge_bg = qcolor("fill_hover")
        badge_fg = qcolor("text_secondary")

        if is_dir:
            pix = get_svg_pixmap("folder", tok("accent"), 40)
            target_x = thumb_area.x() + (thumb_area.width() - 40) // 2
            target_y = thumb_area.y() + (thumb_area.height() - 40) // 2
            painter.drawPixmap(target_x, target_y, pix)
            badge_text = "DIR"
            badge_bg = qcolor("fill_selected")
            badge_fg = qcolor("text_primary")
        else:
            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                pix = self._get_image_thumbnail(path, thumb_area.size())
                if pix and not pix.isNull():
                    target_x = thumb_area.x() + (thumb_area.width() - pix.width()) // 2
                    target_y = thumb_area.y() + (thumb_area.height() - pix.height()) // 2
                    painter.drawPixmap(target_x, target_y, pix)
                else:
                    icon_pix = get_svg_pixmap("image", tok("accent"), 36)
                    painter.drawPixmap(thumb_area.x() + (thumb_area.width() - 36) // 2,
                                       thumb_area.y() + (thumb_area.height() - 36) // 2, icon_pix)
                badge_text = ext.lstrip(".").upper()
                badge_bg = qcolor("fill_selected")
                badge_fg = qcolor("text_primary")
            elif ext in RAW_EXTS:
                icon_pix = get_svg_pixmap("camera", tok("warning"), 36)
                painter.drawPixmap(thumb_area.x() + (thumb_area.width() - 36) // 2,
                                   thumb_area.y() + (thumb_area.height() - 36) // 2, icon_pix)
                badge_text = "RAW"
                badge_bg = qcolor("warning_bg")
                badge_fg = qcolor("warning")
            elif ext in VIDEO_EXTS:
                icon_pix = get_svg_pixmap("video", "#c084fc", 36)
                painter.drawPixmap(thumb_area.x() + (thumb_area.width() - 36) // 2,
                                   thumb_area.y() + (thumb_area.height() - 36) // 2, icon_pix)
                badge_text = ext.lstrip(".").upper()
                badge_bg = QColor("#581c87")
                badge_fg = QColor("#f3e8ff")
            else:
                icon_pix = get_svg_pixmap("file", tok("text_secondary"), 36)
                painter.drawPixmap(thumb_area.x() + (thumb_area.width() - 36) // 2,
                                   thumb_area.y() + (thumb_area.height() - 36) // 2, icon_pix)
                badge_text = ext.lstrip(".").upper() if ext else "FILE"
                badge_bg = qcolor("fill_hover")
                badge_fg = qcolor("text_secondary")

        # ── 3. Draw Badge Pill in Corner ──
        if badge_text:
            badge_font = QFont(painter.font().family(), 6, QFont.Weight.Bold)
            painter.setFont(badge_font)
            fm = QFontMetrics(badge_font)
            badge_w = fm.horizontalAdvance(badge_text) + 8
            badge_h = 14
            badge_rect = QRect(thumb_area.right() - badge_w - 3, thumb_area.top() + 3, badge_w, badge_h)

            painter.setBrush(QBrush(badge_bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge_rect, 3.0, 3.0)

            painter.setPen(badge_fg)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # ── 4. Draw File Name ──
        name_rect = QRect(rect.x() + 6, thumb_area.bottom() + 4, rect.width() - 12, 18)
        title_font = QFont(painter.font().family(), 8, QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(qcolor("text_primary"))

        fm_title = QFontMetrics(title_font)
        elided_name = fm_title.elidedText(path.name, Qt.TextElideMode.ElideMiddle, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, elided_name)

        # ── 5. Draw Subtitle (Size / Count) ──
        sub_rect = QRect(rect.x() + 6, name_rect.bottom() + 1, rect.width() - 12, 14)
        sub_font = QFont(painter.font().family(), 7, QFont.Weight.Normal)
        painter.setFont(sub_font)
        painter.setPen(QColor(tok("accent") if is_selected else tok("text_tertiary")))

        if is_dir:
            sub_text = "Thư mục"
        else:
            try:
                sz = self.model.size(index)
                if sz <= 0 and path.is_file():
                    sz = path.stat().st_size
                if sz >= 1024 * 1024:
                    sub_text = f"{sz / (1024*1024):.1f} MB"
                elif sz >= 1024:
                    sub_text = f"{sz / 1024:.0f} KB"
                else:
                    sub_text = f"{sz} B"
            except Exception:
                sub_text = ""

        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, sub_text)
        painter.restore()

    def _get_image_thumbnail(self, path: Path, max_size: QSize) -> Optional[QPixmap]:
        if path in self._thumb_cache:
            return self._thumb_cache[path]

        if len(self._thumb_cache) >= self._max_cache_size:
            # Drop oldest 50 items
            for _ in range(50):
                self._thumb_cache.pop(next(iter(self._thumb_cache)))

        try:
            target_w = max_size.width() - 8
            target_h = max_size.height() - 8
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            orig_size = reader.size()
            if orig_size.isValid() and (orig_size.width() > target_w * 2 or orig_size.height() > target_h * 2):
                reader.setScaledSize(orig_size.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio))
            qimg = reader.read()
            if not qimg.isNull():
                pix = QPixmap.fromImage(qimg)
                scaled = pix.scaled(
                    target_w, target_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._thumb_cache[path] = scaled
                return scaled
        except Exception:
            pass

        self._thumb_cache[path] = QPixmap()
        return None

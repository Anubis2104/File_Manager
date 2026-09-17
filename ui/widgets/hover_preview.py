"""
ui/widgets/hover_preview.py
Floating hover thumbnail preview popup for table rows and list items.
Renders a 150x150 thumbnail with image dimensions, size, and date info.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QPoint, QSize
from PyQt6.QtGui   import QPixmap, QImage, QImageReader, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGraphicsDropShadowEffect, QApplication,
)

from utils.file_utils import IMAGE_EXTS, VIDEO_EXTS


class HoverThumbnailPopup(QWidget):
    """
    Floating thumbnail preview popup that appears near the cursor
    when hovering over a file row.
    """
    _instance: Optional[HoverThumbnailPopup] = None

    @classmethod
    def instance(cls) -> HoverThumbnailPopup:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._current_path: Optional[Path] = None
        self._pixmap_cache: dict[Path, QPixmap] = {}
        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)

        self.card = QFrame(self)
        self.card.setStyleSheet(
            "QFrame { background-color: #1e1e24; border: 1px solid #0a84ff; "
            "border-radius: 8px; padding: 6px; }"
        )
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(5)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.card.setGraphicsEffect(shadow)

        # Thumbnail display (150x150)
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(150, 150)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet(
            "background-color: #121214; border-radius: 5px; border: 1px solid #2c2c2e;"
        )
        card_layout.addWidget(self.lbl_thumb)

        # Metadata labels
        self.lbl_name = QLabel()
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setFixedWidth(150)
        self.lbl_name.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 8pt;")
        card_layout.addWidget(self.lbl_name)

        self.lbl_meta = QLabel()
        self.lbl_meta.setFixedWidth(150)
        self.lbl_meta.setStyleSheet("color: #8e8e93; font-size: 7.5pt;")
        card_layout.addWidget(self.lbl_meta)

        root_layout.addWidget(self.card)

    def show_preview(self, path: Path, global_pos: QPoint, meta_text: str = ""):
        """Display hover thumbnail at `global_pos`."""
        if not path.exists():
            self.hide()
            return

        self._current_path = path
        self.lbl_name.setText(path.name)
        self.lbl_meta.setText(meta_text)

        # Load thumbnail (cached)
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            pix = self._get_cached_pixmap(path)
            if pix and not pix.isNull():
                scaled = pix.scaled(
                    QSize(150, 150),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.lbl_thumb.setPixmap(scaled)
            else:
                self.lbl_thumb.setText("🖼️\n(Không xem được)")
        elif ext in VIDEO_EXTS:
            self.lbl_thumb.setText("🎬\nVideo")
        else:
            self.lbl_thumb.setText("📄\nTệp tin")

        # Position popup near cursor without going offscreen
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        x = global_pos.x() + 18
        y = global_pos.y() + 18

        self.adjustSize()
        w = self.width()
        h = self.height()

        if screen_geo:
            if x + w > screen_geo.right():
                x = global_pos.x() - w - 10
            if y + h > screen_geo.bottom():
                y = global_pos.y() - h - 10

        self.move(x, y)
        self.show()

    def _get_cached_pixmap(self, path: Path) -> Optional[QPixmap]:
        if path in self._pixmap_cache:
            return self._pixmap_cache[path]

        try:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            reader.setAllocationLimit(0)
            orig_size = reader.size()
            if orig_size.isValid() and not orig_size.isEmpty():
                reader.setScaledSize(orig_size.scaled(QSize(200, 200), Qt.AspectRatioMode.KeepAspectRatio))
            img = reader.read()
            if not img.isNull():
                pix = QPixmap.fromImage(img)
                # Keep cache bounded
                if len(self._pixmap_cache) > 80:
                    self._pixmap_cache.pop(next(iter(self._pixmap_cache)))
                self._pixmap_cache[path] = pix
                return pix
        except Exception:
            pass
        return None

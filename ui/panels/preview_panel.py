"""
ui/panels/preview_panel.py
Right panel: preview of a single selected file (image/video/other).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore  import Qt, QSize
from PyQt6.QtGui   import QPixmap, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea,
    QFrame, QSizePolicy,
)

from utils.file_utils import classify_extension
from utils.media_info import get_media_dimensions
from ui.theme import style


class PreviewPanel(QWidget):
    """Displays a thumbnail and metadata for a single selected file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        hdr = QLabel("  👁  Preview")
        style(hdr, 
            "color: @text_secondary; font-size: 8.5pt; font-weight: 600;"
        )
        layout.addWidget(hdr)

        # Thumbnail label
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedHeight(240)
        style(self.thumb, 
            "background: @fill_hover; border-radius: 10px; color: @text_tertiary;"
        )
        self.thumb.setText("Chọn file để xem preview")
        layout.addWidget(self.thumb)

        # Metadata info
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        style(self.info_label, 
            "color: @text_secondary; font-size: 8.5pt; background: @fill_hover; "
            "border-radius: 8px; padding: 8px;"
        )
        self.info_label.setText("")
        layout.addWidget(self.info_label)
        layout.addStretch()

    def show_file(self, path: Path):
        """Load and display preview + metadata for the given file."""
        media_type = classify_extension(path.suffix)

        if media_type == "image":
            self._show_image(path)
        elif media_type == "raw":
            self._show_raw(path)
        else:
            self._show_generic_icon(path, media_type)

        self._show_metadata(path, media_type)

    def _show_image(self, path: Path):
        try:
            with open(path, "rb") as f:
                data = f.read()
            pix = QPixmap()
            pix.loadFromData(data)
            if pix.isNull():
                self.thumb.setText("⚠ Không thể đọc ảnh")
                return
            scaled = pix.scaled(
                self.thumb.width() - 16,
                self.thumb.height() - 16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb.setPixmap(scaled)
            self.thumb.setText("")
        except Exception as e:
            self.thumb.setText(f"⚠ Lỗi preview: {e}")

    def _show_raw(self, path: Path):
        try:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                try:
                    thumb = raw.extract_thumb()
                    pix = QPixmap()
                    pix.loadFromData(thumb.data)
                    if not pix.isNull():
                        scaled = pix.scaled(
                            self.thumb.width() - 16,
                            self.thumb.height() - 16,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.thumb.setPixmap(scaled)
                        self.thumb.setText("")
                        return
                except Exception:
                    pass
            self._show_image(path)
        except Exception as e:
            self._show_generic_icon(path, "raw")

    def _show_generic_icon(self, path: Path, media_type: str):
        icons = {"video": "🎬", "raw": "📷", "other": "📄"}
        icon = icons.get(media_type, "📄")
        self.thumb.setText(f"{icon}\n\n{path.name}")

        self.thumb.setPixmap(QPixmap())

    def _show_metadata(self, path: Path, media_type: str):
        try:
            stat = path.stat()
            size_kb = stat.st_size / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"

            lines = [
                f"<b>{path.name}</b>",
                f"Loại: {media_type}",
                f"Kích thước: {size_str}",
            ]

            dims = get_media_dimensions(path)
            if dims:
                lines.append(f"Độ phân giải: {dims.width} × {dims.height}")
                lines.append(f"Hướng: {'Ngang (H)' if dims.orientation == 'H' else 'Dọc (V)'}")
                if dims.duration_secs > 0:
                    m, s = divmod(int(dims.duration_secs), 60)
                    lines.append(f"Thời lượng: {m:02d}:{s:02d}")

            from utils.date_utils import extract_best_date
            dt, src = extract_best_date(path)
            if dt:
                src_label = {"exif": "EXIF", "birthtime": "Tạo file", "mtime": "Sửa đổi"}.get(src, src)
                lines.append(f"Ngày ({src_label}): {dt.strftime('%d/%m/%Y %H:%M:%S')}")

            self.info_label.setText("<br>".join(lines))
        except Exception as exc:
            self.info_label.setText(f"Lỗi: {exc}")

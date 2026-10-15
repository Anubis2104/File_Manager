"""
ui/panels/details_pane.py
Explorer's right-hand pane in its two modes:

- "details" (Alt+Shift+P): Shell thumbnail, name, type, then property rows
  (size, dates, dimensions, duration, date taken), or a summary for a multi-selection,
  or the open folder itself when nothing is selected.
- "preview" (Alt+P): the file's content filling the pane: a large Shell thumbnail for
  pictures / videos / documents, the first lines of a text file.

Thumbnails come from ui.thumbnails.ThumbnailCache, so they load off the UI thread and
share the views' cache. Selection changes are coalesced (arrow-key scrolling stays smooth).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QDateTime, QLocale, Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ui.explorer_model import shell_type_name
from ui.theme import style
from ui.thumbnails import ThumbnailCache
from ui.widgets.statusbar import explorer_bytes

DETAILS_THUMB = 256
PREVIEW_THUMB = 768
TEXT_PREVIEW_BYTES = 64 * 1024
MAX_SUMMED = 1000            # don't stat more files than this on the UI thread
TEXT_EXTS = {
    ".txt", ".md", ".log", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg",
    ".toml", ".py", ".js", ".ts", ".css", ".html", ".htm", ".bat", ".ps1", ".sh", ".c", ".h",
    ".cpp", ".hpp", ".java", ".kt", ".go", ".rs", ".sql",
}


def _when(ts: float) -> str:
    return QLocale.system().toString(QDateTime.fromSecsSinceEpoch(int(ts)), QLocale.FormatType.ShortFormat)


def _breakable(name: str) -> str:
    """Let long names like IMG_20240101_123456.jpg wrap (display only; not selectable)."""
    return "".join(ch + "\u200b" if ch in "_-./\\" else ch for ch in name)


def _size_line(size: int) -> str:
    """'4,21 MB (4.414.120 byte)' like the Properties sheet."""
    exact = QLocale.system().toString(size)
    return explorer_bytes(size) if size < 1024 else f"{explorer_bytes(size)} ({exact} byte)"


class DetailsPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "details"
        self._paths: list[Path] = []
        self._folder: Optional[Path] = None
        self._thumb_path: Optional[str] = None
        self._thumb_size = DETAILS_THUMB
        self._debounce = QTimer(self, singleShot=True, interval=60)
        self._debounce.timeout.connect(self._render)
        self._build_ui()
        ThumbnailCache.instance().ready.connect(self._on_thumbnail_ready)    # bound method: safe on destroy

    # ── layout ──

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        # details page
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        style(scroll, "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(6)
        self.thumb = QLabel(page)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(160)
        self.thumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.thumb)
        lay.addSpacing(8)
        self.title = QLabel(page)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        style(self.title, "color: @text_primary; font-size: 14pt; font-weight: 600;")
        lay.addWidget(self.title)
        self.subtitle = QLabel(page)
        self.subtitle.setWordWrap(True)
        style(self.subtitle, "color: @text_secondary;")
        lay.addWidget(self.subtitle)
        lay.addSpacing(12)
        self.props_header = QLabel("Thuộc tính", page)
        style(self.props_header, "color: @text_primary; font-weight: 600;")
        lay.addWidget(self.props_header)
        self._props_holder = QVBoxLayout()
        self._props_holder.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self._props_holder)
        self._props_box: Optional[QWidget] = None
        self._clear_props()
        lay.addStretch(1)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)

        # preview page
        self.preview_image = QLabel(self)
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview_image.setWordWrap(True)
        style(self.preview_image, "color: @text_secondary; padding: 16px;")
        self.preview_text = QPlainTextEdit(self)
        self.preview_text.setReadOnly(True)
        self.preview_text.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        style(self.preview_text, "QPlainTextEdit { background: transparent; color: @text_primary; "
                                 "font-family: Consolas; padding: 8px; }")
        self.stack.addWidget(self.preview_image)
        self.stack.addWidget(self.preview_text)

    # ── API ──

    def set_mode(self, mode: str):
        self.mode = "preview" if mode == "preview" else "details"
        self._render()

    def show_items(self, paths: list[Path], folder: Optional[Path] = None):
        self._paths = [Path(p) for p in paths]
        self._folder = folder
        self._debounce.start()

    def flush(self):
        """Render a pending update now (tests, and right before the pane is shown)."""
        if self._debounce.isActive():
            self._debounce.stop()
            self._render()

    def property_rows(self) -> list[tuple[str, str]]:
        return [(k.text(), v.text()) for k, v in self._rows]

    def title_text(self) -> str:
        return self.title.text().replace("\u200b", "")

    # ── rendering ──

    def _render(self):
        if self.mode == "preview":
            self._render_preview()
        else:
            self.stack.setCurrentIndex(0)
            self._render_details()

    def _render_details(self):
        self._clear_props()
        paths = self._paths
        if len(paths) > 1:
            self._render_many(paths)
        elif paths:
            self._render_one(paths[0])
        elif self._folder is not None:
            self._render_one(self._folder)
        else:
            self._set_thumb(None)
            self.title.setText("")
            self.subtitle.setText("Chọn một mục để xem chi tiết")
            self.props_header.hide()

    def _render_one(self, path: Path):
        self.title.setText(_breakable(path.name or str(path)))
        try:
            st = path.stat()
        except OSError as exc:
            self._set_thumb(None)
            self.subtitle.setText(f"Không đọc được: {exc.strerror or exc}")
            self.props_header.hide()
            return
        is_dir = path.is_dir()
        kind = shell_type_name(path.suffix, is_dir)
        self.subtitle.setText(kind)
        self._set_thumb(path, DETAILS_THUMB)
        self.props_header.show()
        if is_dir:
            n = self._child_count(path)
            if n is not None:
                self._add_prop("Chứa", f"{n} mục" if n < 10000 else "Hơn 10.000 mục")
        else:
            self._add_prop("Kích thước", _size_line(st.st_size))
        self._add_prop("Ngày sửa đổi", _when(st.st_mtime))
        created = getattr(st, "st_birthtime", st.st_ctime)
        self._add_prop("Ngày tạo", _when(created))
        if not is_dir:
            self._add_media_props(path)
        self._add_prop("Vị trí", str(path.parent), copyable=True)

    def _render_many(self, paths: list[Path]):
        self._set_thumb(None)
        self.title.setText(f"{len(paths)} mục được chọn")
        self.props_header.show()
        dirs = sum(1 for p in paths[:MAX_SUMMED] if p.is_dir())
        files = [p for p in paths[:MAX_SUMMED] if p.is_file()]
        kinds = {shell_type_name(p.suffix) for p in files}
        self.subtitle.setText(next(iter(kinds)) if len(kinds) == 1 and not dirs else "Nhiều loại")
        if len(paths) <= MAX_SUMMED and files and not dirs:
            total, newest, oldest = 0, 0.0, None
            for p in files:
                try:
                    st = p.stat()
                except OSError:
                    continue
                total += st.st_size
                newest = max(newest, st.st_mtime)
                oldest = st.st_mtime if oldest is None else min(oldest, st.st_mtime)
            self._add_prop("Tổng kích thước", _size_line(total))
            if oldest is not None:
                span = _when(oldest) if int(oldest) == int(newest) else f"{_when(oldest)} – {_when(newest)}"
                self._add_prop("Ngày sửa đổi", span)
        if dirs:
            self._add_prop("Thư mục", str(dirs))
        if files:
            self._add_prop("Tệp", str(len(files)))

    def _add_media_props(self, path: Path):
        """In-process readers only (Pillow / mutagen): no ExifTool or ffprobe per selection."""
        try:
            from utils.date_utils import get_date_from_mutagen, get_date_from_pillow
            from utils.file_utils import IMAGE_EXTS, RAW_EXTS, VIDEO_EXTS
            from utils.media_info import get_image_dimensions
            ext = path.suffix.lower()
            taken = None
            # RAW: get_image_dimensions falls back to rawpy, which reads the whole file
            if ext in IMAGE_EXTS and ext not in RAW_EXTS:
                dims = get_image_dimensions(path)
                if dims:
                    self._add_prop("Kích thước ảnh", f"{dims.width} x {dims.height}")
                taken = get_date_from_pillow(path)
            elif ext in VIDEO_EXTS:
                taken = get_date_from_mutagen(path)
            if isinstance(taken, datetime):
                self._add_prop("Ngày chụp" if ext in IMAGE_EXTS else "Ngày quay", _when(taken.timestamp()))
        except Exception as exc:                   # metadata is a bonus; the pane must still show
            from utils.safe_log import log_swallowed
            log_swallowed("UI:DetailsPane", exc, f"Không đọc được metadata {path.name}")

    @staticmethod
    def _child_count(path: Path) -> Optional[int]:
        try:
            n = 0
            with os.scandir(path) as it:
                for _ in it:
                    n += 1
                    if n >= 10000:
                        break
            return n
        except OSError:
            return None

    def _render_preview(self):
        paths = self._paths
        target = paths[0] if len(paths) == 1 else None
        if target is None or not target.is_file():
            self._thumb_path = None
            self.preview_image.clear()
            self.preview_image.setText("Chọn một tệp để xem trước" if len(paths) != 1 else "Không có bản xem trước.")
            self.stack.setCurrentIndex(1)
            return
        if target.suffix.lower() in TEXT_EXTS:
            try:
                with open(target, "rb") as f:
                    data = f.read(TEXT_PREVIEW_BYTES)
                self.preview_text.setPlainText(data.decode("utf-8", errors="replace"))
                self.stack.setCurrentIndex(2)
                return
            except OSError as exc:
                self.preview_image.setText(f"Không đọc được tệp: {exc.strerror or exc}")
                self.stack.setCurrentIndex(1)
                return
        self.preview_image.setText("")
        self._set_thumb(target, PREVIEW_THUMB)
        self.stack.setCurrentIndex(1)

    # ── thumbnails ──

    def _thumb_label(self) -> QLabel:
        return self.preview_image if self.mode == "preview" else self.thumb

    def _set_thumb(self, path: Optional[Path], size: int = DETAILS_THUMB):
        label = self._thumb_label()
        if path is None:
            self._thumb_path = None
            label.clear()
            return
        self._thumb_path, self._thumb_size = os.path.normcase(str(path)), size
        pm = ThumbnailCache.instance().get(path, size)
        if pm is not None:
            self._apply_pixmap(pm)
        else:
            label.clear()

    def _on_thumbnail_ready(self, path: str, size: int):
        if os.path.normcase(path) == self._thumb_path and size == self._thumb_size:
            pm = ThumbnailCache.instance().get(path, size)
            if pm is not None:
                self._apply_pixmap(pm)

    def _apply_pixmap(self, pm):
        label = self._thumb_label()
        limit = label.width() - 16 if self.mode == "preview" else min(self.width() - 32, DETAILS_THUMB)
        limit_h = label.height() - 16 if self.mode == "preview" else DETAILS_THUMB
        if limit > 32 and (pm.width() > limit or pm.height() > limit_h):
            pm = pm.scaled(limit, max(32, limit_h), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pm)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._thumb_path:
            pm = ThumbnailCache.instance().get(self._thumb_path, self._thumb_size)
            if pm is not None:
                self._apply_pixmap(pm)

    # ── property rows ──

    def _clear_props(self):
        if self._props_box is not None:
            self._props_box.hide()
            self._props_box.deleteLater()
        self._props_box = QWidget()
        self.props = QGridLayout(self._props_box)
        self.props.setContentsMargins(0, 0, 0, 0)
        self.props.setHorizontalSpacing(12)
        self.props.setVerticalSpacing(6)
        self.props.setColumnStretch(1, 1)
        self._props_holder.addWidget(self._props_box)
        self._rows: list[tuple[QLabel, QWidget]] = []

    def _add_prop(self, key: str, value: str, copyable: bool = False):
        """copyable: a read-only line (long paths scroll instead of widening the pane)."""
        row = len(self._rows)
        k = QLabel(key)
        if copyable:
            v = QLineEdit(value)
            v.setReadOnly(True)
            v.setFrame(False)
            v.setCursorPosition(0)
            v.setToolTip(value)
            v.setMinimumWidth(0)
            v.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            style(v, "QLineEdit { background: transparent; color: @text_primary; padding: 0px; }")
        else:
            v = QLabel(value)
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            style(v, "color: @text_primary;")
        self._rows.append((k, v))
        style(k, "color: @text_secondary;")
        k.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.props.addWidget(k, row, 0)
        self.props.addWidget(v, row, 1)

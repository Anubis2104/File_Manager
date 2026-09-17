"""
ui/widgets/quick_look_dialog.py
QuickLook Modal Viewer for FileManagerPro.
Instant full-screen/modal preview activated via Spacebar (Finder / Peek style).
Supports high-resolution images, RAW photos, video metadata, text files, and keyboard navigation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QEvent
from PyQt6.QtGui import QPixmap, QImage, QKeySequence, QFont, QKeyEvent, QAction
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QFrame, QSizePolicy,
    QPlainTextEdit, QApplication, QGraphicsDropShadowEffect,
)

from ui.widgets.svg_icons import get_svg_icon, get_svg_pixmap
from utils.file_utils import IMAGE_EXTS, VIDEO_EXTS, classify_extension
from utils.media_info import get_media_dimensions
from utils.date_utils import extract_best_date


class QuickLookDialog(QDialog):
    """
    Floating modal preview window.
    Allows rapid inspection of files without opening external applications.
    Press Left / Right to cycle through neighboring files in the active directory.
    """
    file_navigated = pyqtSignal(Path)  # Emitted when user arrows to another file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QuickLook Preview")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(780, 560)
        self.resize(920, 680)

        self.current_path: Optional[Path] = None
        self.file_list: list[Path] = []
        self._current_index: int = -1

        self._build_ui()

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(12, 12, 12, 12)

        # ── Main container frame with dark glassmorphism ──
        self.container = QFrame(self)
        self.container.setObjectName("quickLookContainer")
        self.container.setStyleSheet(
            "#quickLookContainer { "
            "   background-color: rgba(15, 23, 42, 0.96); "
            "   border: 1px solid #334155; "
            "   border-radius: 14px; "
            "}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setColor(Qt.GlobalColor.black)
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        container_lay = QVBoxLayout(self.container)
        container_lay.setContentsMargins(18, 14, 18, 14)
        container_lay.setSpacing(12)

        # ── Header bar ──
        header = QHBoxLayout()
        header.setSpacing(10)

        self.lbl_type_icon = QLabel()
        self.lbl_type_icon.setFixedSize(28, 28)
        header.addWidget(self.lbl_type_icon)

        self.lbl_filename = QLabel("Filename.ext")
        self.lbl_filename.setStyleSheet(
            "color: #f8fafc; font-size: 11pt; font-weight: 600; font-family: 'Segoe UI', 'Inter';"
        )
        self.lbl_filename.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self.lbl_filename)

        # Badges layout
        self.badge_container = QHBoxLayout()
        self.badge_container.setSpacing(6)
        header.addLayout(self.badge_container)

        # Open in default app button
        self.btn_open = QPushButton(" Mở tệp (O)")
        self.btn_open.setIcon(get_svg_icon("external_link", "#38bdf8", 16))
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setStyleSheet(
            "QPushButton { "
            "   background-color: #1e293b; color: #38bdf8; border: 1px solid #334155; "
            "   border-radius: 6px; padding: 5px 12px; font-size: 8.5pt; font-weight: 500; "
            "} "
            "QPushButton:hover { background-color: #334155; border-color: #38bdf8; }"
        )
        self.btn_open.clicked.connect(self._open_in_default_app)
        header.addWidget(self.btn_open)

        # Close button
        self.btn_close = QToolButton()
        self.btn_close.setIcon(get_svg_icon("close", "#94a3b8", 16))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setStyleSheet(
            "QToolButton { background: transparent; border: none; border-radius: 6px; } "
            "QToolButton:hover { background: #334155; }"
        )
        self.btn_close.clicked.connect(self.close)
        header.addWidget(self.btn_close)

        container_lay.addLayout(header)

        # ── Body Display Area ──
        self.body_frame = QFrame()
        self.body_frame.setStyleSheet(
            "background-color: #0b0f19; border: 1px solid #1e293b; border-radius: 10px;"
        )
        self.body_lay = QVBoxLayout(self.body_frame)
        self.body_lay.setContentsMargins(10, 10, 10, 10)
        self.body_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Image preview label
        self.lbl_preview_image = QLabel()
        self.lbl_preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl_preview_image.setStyleSheet("background: transparent; border: none;")
        self.body_lay.addWidget(self.lbl_preview_image)

        # Text preview
        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setStyleSheet(
            "background: transparent; border: none; color: #e2e8f0; font-family: 'Consolas', monospace; font-size: 9pt;"
        )
        self.txt_preview.hide()
        self.body_lay.addWidget(self.txt_preview)

        # Generic metadata info widget
        self.info_widget = QWidget()
        self.info_lay = QVBoxLayout(self.info_widget)
        self.info_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info_icon = QLabel()
        self.lbl_info_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info_text = QLabel()
        self.lbl_info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info_text.setStyleSheet("color: #94a3b8; font-size: 9.5pt;")
        self.info_lay.addWidget(self.lbl_info_icon)
        self.info_lay.addWidget(self.lbl_info_text)
        self.info_widget.hide()
        self.body_lay.addWidget(self.info_widget)

        container_lay.addWidget(self.body_frame, 1)

        # ── Footer Bar ──
        footer = QHBoxLayout()
        self.lbl_counter = QLabel("0 / 0")
        self.lbl_counter.setStyleSheet("color: #64748b; font-size: 8.5pt; font-weight: 500;")
        footer.addWidget(self.lbl_counter)

        footer.addStretch()

        lbl_hint = QLabel("Phím tắt: [← / →] Duyệt file  •  [Space / Esc] Thoát  •  [Enter / O] Mở")
        lbl_hint.setStyleSheet("color: #64748b; font-size: 8.5pt;")
        footer.addWidget(lbl_hint)

        container_lay.addLayout(footer)
        root_lay.addWidget(self.container)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def preview(self, path: Path, file_list: Optional[list[Path]] = None):
        """Open and display QuickLook for `path` within `file_list`."""
        if not path or not path.exists():
            return

        self.file_list = [p for p in (file_list or [path]) if p.is_file()]
        try:
            self._current_index = self.file_list.index(path)
        except ValueError:
            self.file_list.insert(0, path)
            self._current_index = 0

        self._load_file(path)
        self._center_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()

    def _load_file(self, path: Path):
        self.current_path = path
        self.lbl_filename.setText(path.name)
        self.lbl_filename.setToolTip(str(path))

        # Clear badges
        while self.badge_container.count():
            item = self.badge_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Update counter
        total = len(self.file_list)
        cur = self._current_index + 1 if total > 0 else 1
        self.lbl_counter.setText(f"Tệp {cur} / {total}")

        # Hide all body widgets
        self.lbl_preview_image.hide()
        self.txt_preview.hide()
        self.info_widget.hide()

        # File classification
        media_type = classify_extension(path.suffix)
        stat = path.stat()
        size_mb = stat.st_size / (1024 * 1024)
        size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{stat.st_size / 1024:.1f} KB"

        # Add size badge
        self._add_badge(size_str, "#334155", "#cbd5e1")

        if media_type == "image":
            self._render_image(path)
        elif media_type == "raw":
            self._render_raw(path)
        elif media_type == "video":
            self._render_video(path)
        elif path.suffix.lower() in {".txt", ".log", ".json", ".py", ".md", ".csv", ".xml", ".ini", ".yaml", ".yml"}:
            self._render_text(path)
        else:
            self._render_generic(path, media_type)

    def _add_badge(self, text: str, bg_color: str, fg_color: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"background-color: {bg_color}; color: {fg_color}; "
            f"border-radius: 4px; padding: 3px 8px; font-size: 8pt; font-weight: 600;"
        )
        self.badge_container.addWidget(lbl)

    def _render_image(self, path: Path):
        self.lbl_type_icon.setPixmap(get_svg_pixmap("image", "#38bdf8", 24))
        self._add_badge(path.suffix.upper().lstrip("."), "#0369a1", "#ffffff")

        dims = get_media_dimensions(path)
        if dims:
            self._add_badge(f"{dims.width} × {dims.height}", "#1e293b", "#38bdf8")
            if dims.width >= 3840 or dims.height >= 2160:
                self._add_badge("4K UHD", "#065f46", "#34d399")
            elif dims.width >= 1920 or dims.height >= 1080:
                self._add_badge("FHD", "#064e3b", "#6ee7b7")

        try:
            pix = QPixmap(str(path))
            if not pix.isNull():
                avail_w = max(400, self.body_frame.width() - 40)
                avail_h = max(350, self.body_frame.height() - 40)
                scaled = pix.scaled(
                    avail_w, avail_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.lbl_preview_image.setPixmap(scaled)
                self.lbl_preview_image.show()
                return
        except Exception:
            pass

        self._render_generic(path, "image")

    def _render_raw(self, path: Path):
        self.lbl_type_icon.setPixmap(get_svg_pixmap("camera", "#f59e0b", 24))
        self._add_badge("RAW", "#78350f", "#fbbf24")
        self._add_badge(path.suffix.upper().lstrip("."), "#1e293b", "#cbd5e1")

        try:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                thumb = raw.extract_thumb()
                pix = QPixmap()
                pix.loadFromData(thumb.data)
                if not pix.isNull():
                    avail_w = max(400, self.body_frame.width() - 40)
                    avail_h = max(350, self.body_frame.height() - 40)
                    scaled = pix.scaled(
                        avail_w, avail_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.lbl_preview_image.setPixmap(scaled)
                    self.lbl_preview_image.show()
                    return
        except Exception:
            pass

        self._render_generic(path, "raw")

    def _render_video(self, path: Path):
        self.lbl_type_icon.setPixmap(get_svg_pixmap("video", "#a855f7", 24))
        self._add_badge("VIDEO", "#581c87", "#e9d5ff")
        self._add_badge(path.suffix.upper().lstrip("."), "#1e293b", "#cbd5e1")

        dims = get_media_dimensions(path)
        info_lines = [f"<b>{path.name}</b>"]
        if dims:
            info_lines.append(f"Độ phân giải: {dims.width} × {dims.height}")
            if dims.duration_secs > 0:
                m, s = divmod(int(dims.duration_secs), 60)
                dur_str = f"{m:02d}:{s:02d}"
                self._add_badge(dur_str, "#1e293b", "#c084fc")
                info_lines.append(f"Thời lượng: {dur_str}")

        self.lbl_info_icon.setPixmap(get_svg_pixmap("video", "#c084fc", 64))
        self.lbl_info_text.setText("<br>".join(info_lines) + "<br><br><i>Nhấn phím <b>O</b> hoặc <b>Enter</b> để mở video bằng trình phát ngoài</i>")
        self.info_widget.show()

    def _render_text(self, path: Path):
        self.lbl_type_icon.setPixmap(get_svg_pixmap("file", "#38bdf8", 24))
        self._add_badge("TEXT", "#1e293b", "#38bdf8")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(300)]
                content = "".join(lines)
            self.txt_preview.setPlainText(content)
            self.txt_preview.show()
        except Exception as e:
            self._render_generic(path, f"Lỗi đọc text: {e}")

    def _render_generic(self, path: Path, desc: str):
        self.lbl_type_icon.setPixmap(get_svg_pixmap("file", "#94a3b8", 24))
        self._add_badge(path.suffix.upper().lstrip(".") or "FILE", "#1e293b", "#cbd5e1")

        self.lbl_info_icon.setPixmap(get_svg_pixmap("file", "#64748b", 64))
        dt, _ = extract_best_date(path)
        date_str = dt.strftime("%d/%m/%Y %H:%M:%S") if dt else "Không xác định"

        text = (
            f"<b>{path.name}</b><br><br>"
            f"Đường dẫn: {path}<br>"
            f"Định dạng: {desc}<br>"
            f"Thời gian: {date_str}<br><br>"
            f"<i>Nhấn phím <b>O</b> để mở bằng ứng dụng mặc định</i>"
        )
        self.lbl_info_text.setText(text)
        self.info_widget.show()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(x, y)

    def _open_in_default_app(self):
        if self.current_path and self.current_path.exists():
            try:
                os.startfile(str(self.current_path))
            except Exception as e:
                from core.app_logcat import logcat
                logcat.e("QuickLook", f"Không thể mở file {self.current_path}: {e}")

    # ─────────────────────────────────────────────
    # Keyboard Event Handling
    # ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.close()
            event.accept()
        elif key == Qt.Key.Key_Left:
            self._navigate(-1)
            event.accept()
        elif key == Qt.Key.Key_Right:
            self._navigate(1)
            event.accept()
        elif key in (Qt.Key.Key_O, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_in_default_app()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _navigate(self, step: int):
        if not self.file_list or len(self.file_list) <= 1:
            return

        new_idx = (self._current_index + step) % len(self.file_list)
        self._current_index = new_idx
        new_path = self.file_list[new_idx]
        self._load_file(new_path)
        self.file_navigated.emit(new_path)

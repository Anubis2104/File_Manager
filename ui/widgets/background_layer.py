"""
ui/widgets/background_layer.py
Background Layer supporting:
- Static image wallpaper (JPEG, PNG, WebP, BMP)
- Seamless looping muted video wallpaper (MP4, WebM, AVI, MOV)
- Semi-transparent dark overlay tint (adjustable opacity 40% - 95%)
- Non-blocking mouse events (passes all clicks to foreground widgets)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QWidget, QLabel, QStackedLayout, QVBoxLayout
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from core.background_manager import resolve_background_file


class BackgroundLayer(QWidget):
    """
    Background rendering canvas positioned beneath the main window UI.
    Provides wallpaper visuals while remaining completely transparent to mouse input.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._bg_type: str = "none"  # "none" | "image" | "video"
        self._bg_path: Optional[Path] = None
        self._raw_pixmap: Optional[QPixmap] = None
        self._overlay_opacity: float = 0.82

        self._build_ui()

    def _build_ui(self):
        # 1. Video Player & Video Widget
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setMuted(True)
        self.player.setAudioOutput(self.audio_output)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.hide()

        # 2. Image Label
        self.img_label = QLabel(self)
        self.img_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.hide()

        # 3. Tint Overlay Layer
        self.tint_overlay = QWidget(self)
        self.tint_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._update_tint_style()

        self.hide()

    def set_background(self, bg_type: str, bg_file_str: str, opacity: float = 0.82):
        """
        Configure and apply wallpaper.
        bg_type: 'none' | 'image' | 'video'
        bg_file_str: relative or absolute path
        opacity: dark overlay opacity (0.40 to 0.95)
        """
        self._bg_type = bg_type
        self._overlay_opacity = max(0.40, min(0.95, opacity))
        self._update_tint_style()

        resolved = resolve_background_file(bg_file_str)
        self._bg_path = resolved

        if bg_type == "none" or not resolved or not resolved.exists():
            self._stop_video()
            self.video_widget.hide()
            self.img_label.hide()
            self.tint_overlay.hide()
            self.hide()
            return

        self.show()
        self.tint_overlay.show()

        if bg_type == "image":
            self._stop_video()
            self.video_widget.hide()
            self._load_image(resolved)
            self.img_label.show()
        elif bg_type == "video":
            self.img_label.hide()
            self._start_video(resolved)
            self.video_widget.show()

        self._update_geometry()

    def _load_image(self, path: Path):
        try:
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._raw_pixmap = pix
                self._rescale_image()
            else:
                self.img_label.hide()
        except Exception:
            self.img_label.hide()

    def _rescale_image(self):
        if self._raw_pixmap and not self._raw_pixmap.isNull():
            w = max(100, self.width())
            h = max(100, self.height())
            scaled = self._raw_pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.img_label.setPixmap(scaled)

    def _start_video(self, path: Path):
        url = QUrl.fromLocalFile(str(path.resolve()))
        self.player.setSource(url)
        self.player.play()

    def _stop_video(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()

    def _update_tint_style(self):
        # Calculate alpha 0-255 based on opacity
        alpha = int(self._overlay_opacity * 255)
        self.tint_overlay.setStyleSheet(
            f"background-color: rgba(18, 18, 20, {self._overlay_opacity:.2f});"
        )

    def _update_geometry(self):
        r = self.rect()
        self.video_widget.setGeometry(r)
        self.img_label.setGeometry(r)
        self.tint_overlay.setGeometry(r)
        if self._bg_type == "image":
            self._rescale_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()

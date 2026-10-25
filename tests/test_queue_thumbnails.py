"""
tests/test_queue_thumbnails.py
Rename-queue thumbnails are decoded on a worker thread, but QPixmap (a GUI-thread-only
paint device) must only be created on the GUI thread.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    from ui.theme import theme
    if theme()._app is None:
        theme().install(a, mode="dark")
    return a


def _jpeg(path: Path, size=(120, 60)) -> Path:
    from PIL import Image
    Image.new("RGB", size, (30, 120, 220)).save(path)
    return path


def test_worker_emits_qimage_from_its_own_thread(app, tmp_path):
    from ui.panels.right_dock_panel import AsyncThumbnailWorker

    jpg = _jpeg(tmp_path / "a.jpg")
    worker = AsyncThumbnailWorker([jpg])
    received: list[tuple[Path, object, threading.Thread]] = []
    # DirectConnection runs the slot on the emitting (worker) thread, so we see the raw payload
    worker.thumbnail_ready.connect(
        lambda p, img: received.append((p, img, threading.current_thread())),
        Qt.ConnectionType.DirectConnection,
    )

    worker.start()
    assert worker.wait(5000)

    assert len(received) == 1
    path, payload, thread = received[0]
    assert path == jpg
    assert thread is not threading.main_thread()
    assert isinstance(payload, QImage) and not isinstance(payload, QPixmap)
    assert max(payload.width(), payload.height()) == 36


def test_queue_converts_thumbnail_to_pixmap_on_gui_thread(app, tmp_path):
    from ui.panels.right_dock_panel import QueueDockWidget

    jpg = _jpeg(tmp_path / "b.jpg")
    dock = QueueDockWidget()
    image = QImage(36, 18, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)

    dock._on_thumbnail_ready(jpg, image)

    cached = dock._thumb_cache[jpg]
    assert isinstance(cached, QPixmap) and not cached.isNull()
    assert (cached.width(), cached.height()) == (36, 18)
    dock.deleteLater()

"""
ui/thumbnails.py
Asynchronous Explorer thumbnails for the file views.

`ThumbnailCache.instance().get(path, size)` returns a cached QPixmap or None; on a miss
it queues a Shell request (utils.shell_thumbs) on a small thread pool and emits
`ready(path, size)` when the image arrives, so the view repaints just that item.
Keys include the file's mtime, so an edited photo gets a fresh thumbnail.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from utils.shell_thumbs import shell_image

MAX_ENTRIES = 3000          # ~3000 * 96px^2 * 4 B ≈ 110 MB worst case at the largest common size


def _key(path: str, size: int) -> tuple[str, int, int]:
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        mtime = 0
    return (os.path.normcase(path), size, mtime)


class _Signals(QObject):
    done = pyqtSignal(object, str, int, object)     # (key, path, size, QImage | None)


class _Job(QRunnable):
    def __init__(self, key, path: str, size: int, generation: int, owner: "ThumbnailCache"):
        super().__init__()
        self.key, self.path, self.size, self.generation, self.owner = key, path, size, generation, owner
        self.setAutoDelete(True)

    def run(self):
        if self.generation != self.owner._generation:    # folder changed while queued: skip the work
            self.owner._signals.done.emit(self.key, self.path, self.size, None)
            return
        image: Optional[QImage] = shell_image(self.path, self.size)
        self.owner._signals.done.emit(self.key, self.path, self.size, image)


class ThumbnailCache(QObject):
    ready = pyqtSignal(str, int)     # (path, size)

    _instance: Optional["ThumbnailCache"] = None

    def __init__(self):
        super().__init__()
        self._cache: "OrderedDict[tuple, QPixmap]" = OrderedDict()
        self._pending: set[tuple] = set()
        self._generation = 0
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(2, min(4, (os.cpu_count() or 4) // 2)))
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)       # queued: QPixmap is made on the GUI thread

    @classmethod
    def instance(cls) -> "ThumbnailCache":
        if cls._instance is None:
            cls._instance = ThumbnailCache()
        return cls._instance

    def get(self, path: Path | str, size: int) -> Optional[QPixmap]:
        p = str(path)
        key = _key(p, size)
        pm = self._cache.get(key)
        if pm is not None:
            self._cache.move_to_end(key)
            return pm
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_Job(key, p, size, self._generation, self))
        return None

    def cancel_pending(self):
        """Drop queued requests (e.g. on folder change); running ones finish and are discarded."""
        self._generation += 1
        self._pool.clear()
        self._pending.clear()

    def wait_idle(self, msecs: int = 5000) -> bool:
        return self._pool.waitForDone(msecs)

    def _on_done(self, key, path: str, size: int, image):
        self._pending.discard(key)
        if image is None or image.isNull():
            return
        self._cache[key] = QPixmap.fromImage(image)
        self._cache.move_to_end(key)
        while len(self._cache) > MAX_ENTRIES:
            self._cache.popitem(last=False)
        self.ready.emit(path, size)

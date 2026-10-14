"""
ui/clipboard.py
File clipboard compatible with Windows Explorer.

Files go on the clipboard as URLs (Qt exposes them to Windows as CF_HDROP) together
with the shell's "Preferred DropEffect" format, so Cut/Copy here + Paste in Explorer
(and the other way round) move or copy exactly as Explorer would.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtWidgets import QApplication

# How Qt names a native Windows clipboard format inside QMimeData
DROP_EFFECT_FORMAT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
DROPEFFECT_COPY, DROPEFFECT_MOVE, DROPEFFECT_LINK = 1, 2, 4


def set_files(paths: list[Path], cut: bool) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    effect = DROPEFFECT_MOVE if cut else (DROPEFFECT_COPY | DROPEFFECT_LINK)   # Explorer writes 5 for copy
    mime.setData(DROP_EFFECT_FORMAT, struct.pack("<I", effect))
    QApplication.clipboard().setMimeData(mime)


def read_files() -> tuple[list[Path], bool]:
    """(local paths on the clipboard, True if they were cut). ([], False) when none."""
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasUrls():
        return [], False
    paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
    cut = False
    raw = bytes(mime.data(DROP_EFFECT_FORMAT))
    if len(raw) >= 4:
        cut = bool(struct.unpack("<I", raw[:4])[0] & DROPEFFECT_MOVE)
    return paths, cut


def has_files() -> bool:
    return bool(read_files()[0])


def clear_if_cut(paths: list[Path]) -> None:
    """After pasting a cut, Explorer empties the clipboard so the files can't be 'moved' twice."""
    current, cut = read_files()
    key = lambda p: os.path.normcase(os.path.normpath(str(p)))   # Windows paths ignore case
    if cut and {key(p) for p in current} == {key(p) for p in paths}:
        QApplication.clipboard().clear()

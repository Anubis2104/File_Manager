"""
ui/shell.py
Windows Shell look-alikes shared by the Explorer-style widgets: the system icon of a
path (Pictures, Downloads, drives... as Explorer shows them), drive display names
("Local Disk (C:)"), subfolder listings for breadcrumb menus, and Segoe Fluent glyphs.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QFileInfo, QStorageInfo
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QFileIconProvider

# Segoe Fluent Icons code points (Windows 11; Segoe MDL2 Assets on Windows 10)
GLYPH_BACK, GLYPH_FORWARD, GLYPH_UP, GLYPH_REFRESH = "", "", "", ""
GLYPH_CHEVRON_RIGHT, GLYPH_CHEVRON_DOWN = "", ""
GLYPH_SEARCH, GLYPH_CLOSE, GLYPH_ADD = "", "", ""

_icon_provider: Optional[QFileIconProvider] = None


def glyph_font(px: int) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    f.setPixelSize(px)
    return f


def shell_icon(path: Path) -> QIcon:
    """The icon Windows Explorer shows for `path`."""
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    return _icon_provider.icon(QFileInfo(str(path)))


def computer_icon() -> QIcon:
    """'This PC' icon."""
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    return _icon_provider.icon(QFileIconProvider.IconType.Computer)


def is_drive_root(path: Path) -> bool:
    return path.parent == path


def drive_display_name(root: Path) -> str:
    """Explorer-style drive label: 'Data (D:)', or 'Local Disk (C:)' when unlabelled."""
    letter = str(root).rstrip("\\/")
    try:
        label = QStorageInfo(str(root)).displayName()
    except Exception:
        label = ""
    if not label or label.rstrip("\\/") == letter:
        label = "Local Disk"
    return f"{label} ({letter})"


def list_drives() -> list[Path]:
    roots = []
    for s in QStorageInfo.mountedVolumes():
        if s.isValid() and s.isReady():
            roots.append(Path(s.rootPath()))
    return sorted(set(roots), key=lambda p: str(p).lower())


def subfolders(path: Path, limit: int = 400) -> list[Path]:
    """Non-hidden subfolders of `path`, case-insensitively sorted, for breadcrumb menus."""
    out: list[Path] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if len(out) >= limit:
                    break
                try:
                    if not entry.is_dir(follow_symlinks=False) or entry.name.startswith("."):
                        continue
                    if os.name == "nt":
                        attrs = entry.stat(follow_symlinks=False).st_file_attributes
                        if attrs & 0x2 or attrs & 0x4:   # FILE_ATTRIBUTE_HIDDEN / SYSTEM
                            continue
                except OSError:
                    continue
                out.append(Path(entry.path))
    except OSError:
        return []
    return sorted(out, key=lambda p: p.name.lower())

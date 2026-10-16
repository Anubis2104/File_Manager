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


_ADVANCED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"


def _explorer_advanced(name: str, default: int) -> int:
    if os.name != "nt":
        return default
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ADVANCED_KEY) as k:
            return int(winreg.QueryValueEx(k, name)[0])
    except (OSError, ValueError):
        return default


def explorer_shows_hidden() -> bool:
    """View > Show > Hidden items (Advanced key, value Hidden: 1 = show, 2 = hide)."""
    return _explorer_advanced("Hidden", 2) == 1


def explorer_shows_protected_os_files() -> bool:
    """'Hide protected operating system files' unchecked (Advanced key, ShowSuperHidden = 1)."""
    return _explorer_advanced("ShowSuperHidden", 0) == 1


def explorer_hides_extensions() -> bool:
    """'Hide extensions for known file types' (Advanced key, HideFileExt = 1, the default)."""
    return _explorer_advanced("HideFileExt", 1) == 1


def explorer_expands_to_current_folder() -> bool:
    """Navigation pane > 'Expand to open folder' (off by default on Windows 11)."""
    return _explorer_advanced("NavPaneExpandToCurrentFolder", 0) == 1


def _visible(entry: os.DirEntry, show_hidden: bool, show_protected: bool) -> bool:
    """Explorer's rules: Hidden needs 'show hidden items'; Hidden+System (protected OS
    files such as the 'My Documents' / 'Cookies' junctions) also needs ShowSuperHidden."""
    if os.name != "nt":
        return show_hidden or not entry.name.startswith(".")
    attrs = entry.stat(follow_symlinks=False).st_file_attributes
    hidden, system = bool(attrs & 0x2), bool(attrs & 0x4)
    if hidden and system:
        return show_hidden and show_protected
    if hidden:
        return show_hidden
    return True


def subfolders(path: Path, limit: int = 400, show_hidden: Optional[bool] = None,
               show_protected: Optional[bool] = None) -> list[Path]:
    """
    Subfolders of `path` as Explorer lists them, case-insensitively sorted.
    On Windows a leading dot does not hide a folder (".gradle" is shown); the Hidden /
    System attributes do, following Explorer's own view settings unless overridden.
    """
    if show_hidden is None:
        show_hidden = explorer_shows_hidden()
    if show_protected is None:
        show_protected = explorer_shows_protected_os_files()
    out: list[Path] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if len(out) >= limit:
                    break
                try:
                    if entry.is_dir(follow_symlinks=False) and _visible(entry, show_hidden, show_protected):
                        out.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(out, key=lambda p: p.name.lower())


def has_subfolder(path: Path, show_hidden: Optional[bool] = None) -> bool:
    """Cheap check for the navigation pane's expand chevron (stops at the first match)."""
    return bool(subfolders(path, limit=1, show_hidden=show_hidden))


def known_folders() -> list[tuple[str, Path]]:
    """Explorer's default Quick access pins, resolved to their real (possibly OneDrive) paths."""
    from PyQt6.QtCore import QStandardPaths
    L = QStandardPaths.StandardLocation
    out = []
    for label, loc in (("Desktop", L.DesktopLocation), ("Downloads", L.DownloadLocation),
                       ("Documents", L.DocumentsLocation), ("Pictures", L.PicturesLocation),
                       ("Music", L.MusicLocation), ("Videos", L.MoviesLocation)):
        p = QStandardPaths.writableLocation(loc)
        if p and Path(p).is_dir():
            out.append((label, Path(p)))
    return out


def onedrive_root() -> Optional[Path]:
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v and Path(v).is_dir():
            return Path(v)
    return None

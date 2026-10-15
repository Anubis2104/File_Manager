"""
ui/explorer_model.py
QFileSystemModel that presents files the way File Explorer does:

- Name: extension hidden for registered file types when Explorer's
  "Hide extensions for known file types" is on (the Windows default);
- Size: whole kilobytes rounded up with digit grouping ("1,234 KB"), blank for folders;
- Date modified: the system's short date/time format;
- Type: the registered Windows type name ("JPG File", "Text Document", "File folder"),
  not Qt's MIME description ("Joint Photographic Experts Group", "text/plain");
- Vietnamese column headers, like the rest of the app;
- secondary columns in the secondary text color.

Only display roles change: filePath(), EditRole and renames still use real names.
"""
from __future__ import annotations

import math
import os
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import QLocale, QModelIndex, Qt
from PyQt6.QtGui import QFileSystemModel

from ui.theme import qcolor

COL_NAME, COL_SIZE, COL_TYPE, COL_DATE = 0, 1, 2, 3


@lru_cache(maxsize=1024)
def _is_registered_type(ext: str) -> bool:
    """Explorer hides only extensions that have a registered file type (HKCR\\.ext)."""
    if os.name != "nt" or not ext:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext):
            return True
    except OSError:
        return False


def explorer_display_name(name: str, is_dir: bool, hide_extensions: bool) -> str:
    if is_dir or not hide_extensions:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:                        # ".gitignore", "README"
        return name
    return stem if _is_registered_type("." + ext.lower()) else name


@lru_cache(maxsize=2048)
def shell_type_name(ext: str, is_dir: bool = False) -> str:
    """Windows' type name for an extension (SHGetFileInfoW + SHGFI_TYPENAME), '' if unknown."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]

    SHGFI_TYPENAME, SHGFI_USEFILEATTRIBUTES = 0x400, 0x10
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_NORMAL = 0x10, 0x80
    info = SHFILEINFOW()
    name = "folder" if is_dir else f"file{ext}"          # USEFILEATTRIBUTES: the file need not exist
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
    ctypes.windll.shell32.SHGetFileInfoW.restype = ctypes.c_size_t      # DWORD_PTR
    ok = ctypes.windll.shell32.SHGetFileInfoW(name, attrs, ctypes.byref(info), ctypes.sizeof(info),
                                             SHGFI_TYPENAME | SHGFI_USEFILEATTRIBUTES)
    return info.szTypeName if ok else ""


HEADERS = {COL_NAME: "Tên", COL_SIZE: "Kích thước", COL_TYPE: "Loại", COL_DATE: "Ngày sửa đổi"}


def explorer_size_text(size: int, locale: Optional[QLocale] = None) -> str:
    kb = math.ceil(size / 1024) if size > 0 else 0
    return f"{(locale or QLocale.system()).toString(kb)} KB"


class ExplorerFileSystemModel(QFileSystemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ui.shell import explorer_hides_extensions
        self.hide_extensions = explorer_hides_extensions()
        self._locale = QLocale.system()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return super().data(index, role)
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return explorer_display_name(self.fileName(index), self.isDir(index), self.hide_extensions)
            if col == COL_SIZE:
                return "" if self.isDir(index) else explorer_size_text(self.size(index), self._locale)
            if col == COL_DATE:
                return self._locale.toString(self.lastModified(index), QLocale.FormatType.ShortFormat)
            if col == COL_TYPE:
                is_dir = self.isDir(index)
                ext = "" if is_dir else os.path.splitext(self.fileName(index))[1].lower()
                return shell_type_name(ext, is_dir) or super().data(index, role)
        elif role == Qt.ItemDataRole.ForegroundRole and col != COL_NAME:
            return qcolor("text_secondary")
        elif role == Qt.ItemDataRole.TextAlignmentRole and col == COL_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return super().data(index, role)

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole and section in HEADERS:
            return HEADERS[section]
        return super().headerData(section, orientation, role)

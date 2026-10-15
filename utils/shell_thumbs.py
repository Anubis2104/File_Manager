"""
utils/shell_thumbs.py
Thumbnails and icons exactly as File Explorer shows them, from the Windows Shell
(IShellItemImageFactory::GetImage): photo/video/PDF previews from the system thumbnail
cache and codecs, folder previews, and file-type icons for everything else.

Called through the COM vtable with ctypes (no extra dependency). Safe to call from
worker threads: each call makes sure COM is initialised on the calling thread.
Returns QImage (not QPixmap), which may be created off the GUI thread.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_int, c_long, c_ubyte, c_ulong, c_ushort, c_void_p
from pathlib import Path
from typing import Optional

from PyQt6.QtGui import QImage

IS_WINDOWS = sys.platform == "win32"

# SIIGBF flags
RESIZE_TO_FIT, BIGGER_SIZE_OK, MEMORY_ONLY, ICON_ONLY, THUMBNAIL_ONLY = 0x0, 0x1, 0x2, 0x4, 0x8
IN_CACHE_ONLY, CROP_TO_SQUARE, SCALE_UP = 0x10, 0x20, 0x100


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        import uuid
        u = uuid.UUID(text)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
        g.Data4[:] = list(u.bytes[8:])
        return g


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", c_long), ("cy", c_long)]


if IS_WINDOWS:
    from ctypes import wintypes
    _IID_IShellItemImageFactory = _GUID.parse("bcc18b79-ba16-442f-80c4-8a59c30c463b")
    _shell32 = ctypes.windll.shell32
    _ole32 = ctypes.windll.ole32
    _gdi32 = ctypes.windll.gdi32
    _shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    _shell32.SHCreateItemFromParsingName.restype = c_long
    _gdi32.DeleteObject.argtypes = [c_void_p]
    _gdi32.GetObjectW.argtypes = [c_void_p, c_int, c_void_p]
    _gdi32.GetDIBits.argtypes = [c_void_p, c_void_p, wintypes.UINT, wintypes.UINT, c_void_p, c_void_p, wintypes.UINT]
    _GetImage = ctypes.WINFUNCTYPE(c_long, c_void_p, _SIZE, c_int, POINTER(c_void_p))
    _Release = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
    _COINIT_APARTMENTTHREADED = 0x2
    ctypes.windll.user32.GetDC.restype = c_void_p           # HDC is pointer-sized
    ctypes.windll.user32.GetDC.argtypes = [c_void_p]
    ctypes.windll.user32.ReleaseDC.argtypes = [c_void_p, c_void_p]


def shell_image(path: Path | str, size: int, flags: int = RESIZE_TO_FIT) -> Optional[QImage]:
    """
    The Explorer image for `path` fitted into size x size px: a thumbnail when the Shell
    has one, else the file-type icon (pass THUMBNAIL_ONLY / ICON_ONLY to force either).
    None when unavailable (not Windows, missing file, THUMBNAIL_ONLY without a thumbnail).
    """
    if not IS_WINDOWS:
        return None
    _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)   # S_FALSE if already initialised
    factory = c_void_p()
    # Parsing names need backslashes: Qt (QFileSystemModel.filePath) hands out "C:/..." paths,
    # which SHCreateItemFromParsingName rejects with E_INVALIDARG.
    native = os.path.normpath(str(path))
    hr = _shell32.SHCreateItemFromParsingName(native, None, byref(_IID_IShellItemImageFactory), byref(factory))
    if hr < 0 or not factory:
        return None
    vtbl = ctypes.cast(factory, POINTER(POINTER(c_void_p)))[0]
    hbitmap = c_void_p()
    try:
        hr = _GetImage(vtbl[3])(factory, _SIZE(size, size), flags, byref(hbitmap))   # IShellItemImageFactory::GetImage
    finally:
        _Release(vtbl[2])(factory)                                                     # IUnknown::Release
    if hr < 0 or not hbitmap:
        return None
    try:
        return _hbitmap_to_qimage(hbitmap)
    finally:
        _gdi32.DeleteObject(hbitmap)


def _hbitmap_to_qimage(hbitmap: c_void_p) -> Optional[QImage]:
    """
    32-bit DIB -> QImage keeping transparency. (QImage.fromHBITMAP drops the alpha
    channel, which turns icon backgrounds black.) Shell icons come premultiplied;
    photo thumbnails often carry an all-zero alpha byte, meaning "opaque".
    """
    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", c_long), ("bmWidth", c_long), ("bmHeight", c_long), ("bmWidthBytes", c_long),
                    ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD), ("bmBits", c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", c_long), ("biHeight", c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", c_long), ("biYPelsPerMeter", c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bm = BITMAP()
    if not _gdi32.GetObjectW(hbitmap, ctypes.sizeof(bm), byref(bm)) or bm.bmWidth <= 0 or bm.bmHeight == 0:
        return None
    w, h = bm.bmWidth, abs(bm.bmHeight)
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # top-down BGRA
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = ctypes.windll.user32.GetDC(None)
    try:
        lines = _gdi32.GetDIBits(hdc, hbitmap, 0, h, buf, byref(header), 0)
    finally:
        ctypes.windll.user32.ReleaseDC(None, hdc)
    if lines != h:
        return None
    raw = buf.raw
    has_alpha = any(raw[3::4])
    fmt = QImage.Format.Format_ARGB32_Premultiplied if has_alpha else QImage.Format.Format_RGB32
    return QImage(raw, w, h, w * 4, fmt).copy()     # copy(): own the pixels before `buf` goes away


def has_shell_thumbnail(path: Path | str, size: int = 96) -> bool:
    """True when the Shell has a real thumbnail (not just an icon) for `path`."""
    return shell_image(path, size, THUMBNAIL_ONLY) is not None

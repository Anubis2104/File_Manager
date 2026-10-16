"""
utils/shell_menu.py
The real Windows Shell context menu ("Show more options"): the same verbs Explorer
shows, including those added by other apps (7-Zip, Open with, Send to, Defender...).

COM is called through vtables with ctypes:
    SHParseDisplayName -> SHBindToParent -> IShellFolder::GetUIObjectOf -> IContextMenu
    (background of a folder: IShellFolder::CreateViewObject -> IContextMenu)
Owner-drawn submenus (Open with, Send to) need their menu messages forwarded to
IContextMenu3::HandleMenuMsg2 — MainWindow.nativeEvent calls `active_menu_message`
while a menu is open.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_int, c_long, c_size_t, c_ssize_t, c_uint, c_ulong, c_void_p, c_wchar_p
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

CMD_FIRST, CMD_LAST = 1, 0x7FFF
CMF_NORMAL, CMF_EXPLORE, CMF_EXTENDEDVERBS = 0x0, 0x4, 0x100
GCS_VERBW = 0x4
CMIC_MASK_UNICODE, CMIC_MASK_PTINVOKE, CMIC_MASK_FLAG_NO_UI = 0x4000, 0x20000000, 0x400
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2
HOST_VERBS = {"rename"}          # the Shell asks the hosting view to do these; the caller handles them
_HR_CANCELLED = 0x800704C7        # HRESULT_FROM_WIN32(ERROR_CANCELLED): the user closed a dialog
WM_INITMENUPOPUP, WM_DRAWITEM, WM_MEASUREITEM, WM_MENUCHAR = 0x0117, 0x002B, 0x002C, 0x0120
FORWARDED_MESSAGES = {WM_INITMENUPOPUP, WM_DRAWITEM, WM_MEASUREITEM, WM_MENUCHAR}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        import uuid
        u = uuid.UUID(text)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
        g.Data4[:] = list(u.bytes[8:])
        return g


IID_IShellFolder = _GUID.parse("000214E6-0000-0000-C000-000000000046")
IID_IContextMenu = _GUID.parse("000214E4-0000-0000-C000-000000000046")
IID_IContextMenu2 = _GUID.parse("000214F4-0000-0000-C000-000000000046")
IID_IContextMenu3 = _GUID.parse("BCFCE0A0-EC17-11D0-8D10-00A0C90F2719")


class _POINT(ctypes.Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class CMINVOKECOMMANDINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("fMask", ctypes.c_uint32), ("hwnd", c_void_p),
                ("lpVerb", c_void_p), ("lpParameters", c_void_p), ("lpDirectory", c_void_p),
                ("nShow", c_int), ("dwHotKey", ctypes.c_uint32), ("hIcon", c_void_p),
                ("lpTitle", c_void_p), ("lpVerbW", c_void_p), ("lpParametersW", c_void_p),
                ("lpDirectoryW", c_wchar_p), ("lpTitleW", c_void_p), ("ptInvoke", _POINT)]


if IS_WINDOWS:
    _shell32, _ole32, _user32 = ctypes.windll.shell32, ctypes.windll.ole32, ctypes.windll.user32
    _shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p), c_ulong, POINTER(c_ulong)]
    _shell32.SHParseDisplayName.restype = c_long
    _shell32.SHBindToParent.argtypes = [c_void_p, POINTER(_GUID), POINTER(c_void_p), POINTER(c_void_p)]
    _shell32.SHBindToParent.restype = c_long
    _shell32.SHGetDesktopFolder.argtypes = [POINTER(c_void_p)]
    _shell32.SHGetDesktopFolder.restype = c_long
    _ole32.CoTaskMemFree.argtypes = [c_void_p]
    _ole32.CoInitializeEx.argtypes, _ole32.CoInitializeEx.restype = [c_void_p, c_ulong], c_long
    _ole32.CoUninitialize.argtypes, _ole32.CoUninitialize.restype = [], None
    _user32.CreatePopupMenu.restype = c_void_p
    _user32.DestroyMenu.argtypes = [c_void_p]
    _user32.GetMenuItemCount.argtypes = [c_void_p]
    _user32.TrackPopupMenuEx.argtypes = [c_void_p, c_uint, c_int, c_int, c_void_p, c_void_p]
    _user32.TrackPopupMenuEx.restype = c_int
    _user32.SetForegroundWindow.argtypes = [c_void_p]

    _QI = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(_GUID), POINTER(c_void_p))
    _Release = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
    _BindToObject = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, c_void_p, POINTER(_GUID), POINTER(c_void_p))
    _CreateViewObject = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, POINTER(_GUID), POINTER(c_void_p))
    _GetUIObjectOf = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, c_uint, POINTER(c_void_p), POINTER(_GUID),
                                        POINTER(c_uint), POINTER(c_void_p))
    _QueryContextMenu = ctypes.WINFUNCTYPE(c_long, c_void_p, c_void_p, c_uint, c_uint, c_uint, c_uint)
    _InvokeCommand = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(CMINVOKECOMMANDINFOEX))
    _GetCommandString = ctypes.WINFUNCTYPE(c_long, c_void_p, c_size_t, c_uint, POINTER(c_uint), c_void_p, c_uint)
    _HandleMenuMsg = ctypes.WINFUNCTYPE(c_long, c_void_p, c_uint, c_size_t, c_ssize_t)
    _HandleMenuMsg2 = ctypes.WINFUNCTYPE(c_long, c_void_p, c_uint, c_size_t, c_ssize_t, POINTER(c_ssize_t))


def _vt(obj: c_void_p, index: int):
    return ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0][index]


def _release(obj: Optional[c_void_p]):
    if obj:
        _Release(_vt(obj, 2))(obj)


_active: Optional["ShellContextMenu"] = None


def active_menu_message(msg: int, wparam: int, lparam: int) -> Optional[int]:
    """Forward an owner-draw/menu message to the open Shell menu. Returns LRESULT if handled."""
    if _active is None or msg not in FORWARDED_MESSAGES:
        return None
    return _active.handle_menu_message(msg, wparam, lparam)


class ShellContextMenu:
    """
    Context menu of `paths` (all in the same folder) or, with background=True, of the
    folder `paths[0]` itself as seen from inside (New, Paste, View...).
    """

    def __init__(self, paths: list[Path], hwnd: int = 0, background: bool = False, extended: bool = False):
        if not IS_WINDOWS:
            raise OSError("Shell context menus need Windows")
        self.hwnd = c_void_p(hwnd or None)
        self.extended = extended
        self._pidls: list[c_void_p] = []
        self._cm = c_void_p()
        self._cm2 = c_void_p()
        self._cm3 = c_void_p()
        self._hmenu: Optional[int] = None
        hr = _ole32.CoInitializeEx(None, 0x2)          # S_OK / S_FALSE: STA, balanced in close()
        if hr < 0:                                      # RPC_E_CHANGED_MODE: an MTA thread can't host menus
            raise OSError(f"COM apartment unavailable (hr=0x{hr & 0xFFFFFFFF:08X})")
        self._com_initialized = True
        folder = None
        try:
            if background:
                folder = self._folder_object(Path(paths[0]))
                hr = _CreateViewObject(_vt(folder, 8))(folder, self.hwnd, byref(IID_IContextMenu), byref(self._cm))
            else:
                folder, children = self._parent_and_children(paths)
                arr = (c_void_p * len(children))(*children)
                hr = _GetUIObjectOf(_vt(folder, 10))(folder, self.hwnd, len(children), arr,
                                                    byref(IID_IContextMenu), None, byref(self._cm))
            if hr < 0 or not self._cm:
                raise OSError(f"IContextMenu unavailable (hr=0x{hr & 0xFFFFFFFF:08X})")
            _QI(_vt(self._cm, 0))(self._cm, byref(IID_IContextMenu3), byref(self._cm3))
            if not self._cm3:
                _QI(_vt(self._cm, 0))(self._cm, byref(IID_IContextMenu2), byref(self._cm2))
        except Exception:
            self.close()
            raise
        finally:
            _release(folder)

    # ── construction helpers ──

    def _parse(self, path: Path) -> c_void_p:
        pidl = c_void_p()
        hr = _shell32.SHParseDisplayName(os.path.normpath(str(path)), None, byref(pidl), 0, None)
        if hr < 0 or not pidl:
            raise OSError(f"Cannot resolve {path} (hr=0x{hr & 0xFFFFFFFF:08X})")
        self._pidls.append(pidl)
        return pidl

    def _parent_and_children(self, paths: list[Path]):
        parent = Path(paths[0]).parent
        if any(Path(p).parent != parent for p in paths):            # one IShellFolder per menu
            raise ValueError("Shell context menu items must share one folder")
        folder, children = None, []
        for p in paths:
            pidl = self._parse(Path(p))
            psf, child = c_void_p(), c_void_p()
            hr = _shell32.SHBindToParent(pidl, byref(IID_IShellFolder), byref(psf), byref(child))
            if hr < 0:
                raise OSError(f"SHBindToParent failed for {p}")
            if folder is None:
                folder = psf
            else:
                _release(psf)
            children.append(child.value)                            # points into `pidl`, kept alive
        return folder, children

    def _folder_object(self, folder: Path) -> c_void_p:
        desktop = c_void_p()
        hr = _shell32.SHGetDesktopFolder(byref(desktop))
        if hr < 0 or not desktop:
            raise OSError(f"SHGetDesktopFolder failed (hr=0x{hr & 0xFFFFFFFF:08X})")
        try:
            pidl = self._parse(folder)
            psf = c_void_p()
            hr = _BindToObject(_vt(desktop, 5))(desktop, pidl, None, byref(IID_IShellFolder), byref(psf))
            if hr < 0 or not psf:
                raise OSError(f"Cannot bind to {folder}")
            return psf
        finally:
            _release(desktop)

    # ── menu ──

    def build(self) -> int:
        """Fill a native popup menu (once); returns the HMENU."""
        if self._hmenu is None:
            self._hmenu = _user32.CreatePopupMenu()
            flags = CMF_NORMAL | CMF_EXPLORE | (CMF_EXTENDEDVERBS if self.extended else 0)
            hr = _QueryContextMenu(_vt(self._cm, 3))(self._cm, self._hmenu, 0, CMD_FIRST, CMD_LAST, flags)
            if hr < 0:
                raise OSError("QueryContextMenu failed")
        return self._hmenu

    def item_count(self) -> int:
        return _user32.GetMenuItemCount(self.build())

    def verb(self, cmd_id: int) -> str:
        buf = ctypes.create_unicode_buffer(260)
        hr = _GetCommandString(_vt(self._cm, 5))(self._cm, cmd_id - CMD_FIRST, GCS_VERBW, None,
                                                ctypes.cast(buf, c_void_p), 260)
        return buf.value if hr >= 0 else ""

    def verbs(self) -> set[str]:
        """Canonical verbs ('open', 'copy', 'delete', 'properties', ...) present in the menu."""
        self.build()
        found = set()
        for cmd in range(CMD_FIRST, CMD_FIRST + 400):
            v = self.verb(cmd)
            if v:
                found.add(v.lower())
        return found

    def show(self, x: int, y: int) -> Optional[str]:
        """Show the menu at physical screen (x, y); run the chosen command. Returns its verb."""
        global _active
        hmenu = self.build()
        _user32.SetForegroundWindow(self.hwnd)       # TrackPopupMenu requirement (menu closes properly)
        _active = self
        try:
            cmd = _user32.TrackPopupMenuEx(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, x, y, self.hwnd, None)
        finally:
            _active = None
        if cmd <= 0:
            return None
        verb = self.verb(cmd)
        if verb.lower() not in HOST_VERBS:
            self.invoke(cmd, x, y)
        return verb.lower() or str(cmd)

    def invoke(self, cmd_or_verb, x: int = 0, y: int = 0, no_ui: bool = False, directory: Optional[Path] = None):
        info = CMINVOKECOMMANDINFOEX()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE | (CMIC_MASK_FLAG_NO_UI if no_ui else 0)
        info.hwnd = self.hwnd
        info.nShow = 1                                  # SW_SHOWNORMAL
        info.ptInvoke = _POINT(x, y)
        if directory is not None:
            info.lpDirectoryW = os.path.normpath(str(directory))
        if isinstance(cmd_or_verb, str):
            self.build()
            a = ctypes.create_string_buffer(cmd_or_verb.encode("ascii"))
            w = ctypes.create_unicode_buffer(cmd_or_verb)
            info.lpVerb = ctypes.cast(a, c_void_p)
            info.lpVerbW = ctypes.cast(w, c_void_p)
        else:
            info.lpVerb = info.lpVerbW = cmd_or_verb - CMD_FIRST      # MAKEINTRESOURCE(offset)
        hr = _InvokeCommand(_vt(self._cm, 4))(self._cm, byref(info))
        if hr < 0 and (hr & 0xFFFFFFFF) != _HR_CANCELLED:
            raise OSError(f"InvokeCommand failed (hr=0x{hr & 0xFFFFFFFF:08X})")

    def handle_menu_message(self, msg: int, wparam: int, lparam: int) -> Optional[int]:
        if self._cm3:
            res = c_ssize_t(0)                         # LRESULT is signed; Qt takes a qintptr
            if _HandleMenuMsg2(_vt(self._cm3, 7))(self._cm3, msg, wparam, lparam, byref(res)) >= 0:
                return res.value
        elif self._cm2 and msg != WM_MENUCHAR:
            if _HandleMenuMsg(_vt(self._cm2, 6))(self._cm2, msg, wparam, lparam) >= 0:
                return 0
        return None

    def close(self):
        if self._hmenu:
            _user32.DestroyMenu(self._hmenu)
            self._hmenu = None
        for obj in (self._cm3, self._cm2, self._cm):
            _release(obj)
        self._cm = self._cm2 = self._cm3 = c_void_p()
        for pidl in self._pidls:
            _ole32.CoTaskMemFree(pidl)
        self._pidls.clear()
        if getattr(self, "_com_initialized", False):
            self._com_initialized = False
            _ole32.CoUninitialize()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

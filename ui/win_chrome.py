"""
ui/win_chrome.py
Windows 11 window chrome for a QMainWindow, the way File Explorer / WinUI
"ExtendsContentIntoTitleBar" apps do it:

- the native frame is kept (NOT Qt's FramelessWindowHint: a frameless translucent Qt
  window becomes WS_EX_LAYERED, whose transparent pixels are click-through and get no
  Mica or caption buttons), so the window keeps its shadow, rounded corners, Aero Snap,
  resize borders and minimize/maximize animations;
- WM_NCCALCSIZE extends the client area over the title bar (Qt follows via WM_SIZE);
- the minimize / maximize / close buttons are the real ones drawn by DWM in the
  extended frame (DwmDefWindowProc): Snap Layouts, hover states and dark mode for free;
- our title bar (tabs) answers WM_NCHITTEST: empty space is HTCAPTION (drag,
  double-click to maximize, Alt+Space menu);
- a Mica Alt backdrop (DWMSBT_TABBEDWINDOW, as in Explorer) shows through transparent
  chrome areas, with the frame's dark/light mode matching the app theme.

Everything is a no-op off Windows or when a call is unsupported (Windows 10 has no Mica).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable, Optional

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QAbstractButton, QWidget

IS_WINDOWS = sys.platform == "win32"

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x20, 0x2, 0x1, 0x4, 0x10

DWMWA_CAPTION_BUTTON_BOUNDS = 5
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROPS = {"none": 1, "mica": 2, "acrylic": 3, "tabbed": 4}   # DWM_SYSTEMBACKDROP_TYPE


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi
    _dwmapi.DwmDefWindowProc.restype = wintypes.BOOL
    _dwmapi.DwmDefWindowProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                         wintypes.LPARAM, ctypes.POINTER(ctypes.c_ssize_t)]


def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    try:
        v = ctypes.c_int(value)
        return _dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
    except Exception:
        return False


def _frame_thickness(hwnd: int) -> tuple[int, int]:
    """Physical-pixel resize-frame thickness (what a maximized window overhangs the screen by)."""
    try:
        dpi = _user32.GetDpiForWindow(wintypes.HWND(hwnd))
        pad = _user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
        return (_user32.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi) + pad,
                _user32.GetSystemMetricsForDpi(SM_CYSIZEFRAME, dpi) + pad)
    except Exception:
        pad = _user32.GetSystemMetrics(SM_CXPADDEDBORDER)
        return _user32.GetSystemMetrics(SM_CXSIZEFRAME) + pad, _user32.GetSystemMetrics(SM_CYSIZEFRAME) + pad


class WindowChrome:
    """
    Wires native hit-testing, DWM caption buttons and backdrop for a framed top-level
    window with Qt.WidgetAttribute.WA_TranslucentBackground.

    title_bar: widget whose empty area drags the window.
    is_interactive(widget) -> bool: True for title-bar children that must keep receiving
               clicks (tabs, buttons). Default: any QAbstractButton.
    """

    RESIZE_BORDER = 6   # logical px, inside the window edge

    def __init__(self, window: QWidget, title_bar: QWidget,
                 is_interactive: Optional[Callable[[QWidget], bool]] = None):
        self.window = window
        self.title_bar = title_bar
        self.is_interactive = is_interactive or (lambda w: isinstance(w, QAbstractButton))
        self.enabled = False

    # ── setup ────────────────────────────────────────────────────────────

    def install(self, dark: bool, backdrop: str = "tabbed") -> bool:
        if not IS_WINDOWS:
            return False
        hwnd = wintypes.HWND(int(self.window.winId()))
        # Must be on before SWP_FRAMECHANGED: that call sends WM_NCCALCSIZE synchronously
        self.enabled = True
        try:
            # Whole client area is "glass": transparent pixels show the system backdrop
            _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(-1, -1, -1, -1)))
            _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                 SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            self.enabled = False
            return False
        self.set_backdrop(backdrop, dark)
        return True

    def set_backdrop(self, kind: str, dark: bool) -> bool:
        """kind: 'tabbed' (Mica Alt) | 'mica' | 'acrylic' | 'none'. Returns False if unsupported."""
        if not IS_WINDOWS:
            return False
        hwnd = int(self.window.winId())
        _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        return _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROPS.get(kind, 1))

    def caption_buttons_width(self) -> int:
        """Logical width reserved by the DWM caption buttons (0 if unknown)."""
        if not (IS_WINDOWS and self.enabled):
            return 0
        r = wintypes.RECT()
        hr = _dwmapi.DwmGetWindowAttribute(wintypes.HWND(int(self.window.winId())), DWMWA_CAPTION_BUTTON_BOUNDS,
                                           ctypes.byref(r), ctypes.sizeof(r))
        if hr != 0:
            return 0
        dpr = self.window.devicePixelRatioF() or 1.0
        return int(round((r.right - r.left) / dpr))

    # ── message handling (call from QMainWindow.nativeEvent) ────────────

    def native_event(self, message) -> tuple[bool, int]:
        if not self.enabled:
            return False, 0
        msg = wintypes.MSG.from_address(int(message))

        # DWM owns the caption buttons: hover, press, click, Snap Layouts
        lres = ctypes.c_ssize_t(0)
        if _dwmapi.DwmDefWindowProc(msg.hWnd, msg.message, msg.wParam, msg.lParam, ctypes.byref(lres)):
            return True, lres.value

        if msg.message == WM_NCCALCSIZE and msg.wParam:
            if self.window.isMaximized():
                # A maximized window overhangs the monitor by the frame thickness
                params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                fx, fy = _frame_thickness(int(self.window.winId()))
                r = params.rgrc[0]
                r.left += fx; r.right -= fx; r.top += fy; r.bottom -= fy
            return True, 0   # client area = whole window (no native caption bar)

        if msg.message == WM_NCHITTEST:
            return True, self._hit_test(msg.hWnd, msg.lParam)
        return False, 0

    def _hit_test(self, hwnd, lparam: int) -> int:
        # Use the message's point (physical screen px), not the current cursor position:
        # WindowFromPoint / SendMessage probes ask about arbitrary points.
        sx = ctypes.c_short(lparam & 0xFFFF).value
        sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        origin = wintypes.POINT(0, 0)
        _user32.ClientToScreen(hwnd, ctypes.byref(origin))
        dpr = self.window.devicePixelRatioF() or 1.0
        w = self.window
        pos = QPoint(int((sx - origin.x) / dpr), int((sy - origin.y) / dpr))
        x, y, width, height = pos.x(), pos.y(), w.width(), w.height()

        if not w.isMaximized() and not w.isFullScreen():
            b = self.RESIZE_BORDER
            left, right, top, bottom = x < b, x >= width - b, y < b, y >= height - b
            if top and left: return HTTOPLEFT
            if top and right: return HTTOPRIGHT
            if bottom and left: return HTBOTTOMLEFT
            if bottom and right: return HTBOTTOMRIGHT
            if left: return HTLEFT
            if right: return HTRIGHT
            if top: return HTTOP
            if bottom: return HTBOTTOM

        if self.title_bar.isVisible() and self._rect_in_window(self.title_bar).contains(pos):
            child = w.childAt(pos)
            while child is not None and child is not self.title_bar:
                if self.is_interactive(child):
                    return HTCLIENT
                child = child.parentWidget()
            return HTCAPTION
        return HTCLIENT

    def _rect_in_window(self, widget: QWidget) -> QRect:
        return QRect(widget.mapTo(self.window, QPoint(0, 0)), widget.size())

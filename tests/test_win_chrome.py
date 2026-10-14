"""
tests/test_win_chrome.py
Explorer-style window chrome on a REAL Windows window (not the offscreen platform):
the app runs in a subprocess with the native "windows" Qt platform and reports what
Windows itself says about its window: styles, client area, WM_NCHITTEST answers,
caption-button bounds and the maximized client rect.

Skipped off Windows and when FMPRO_SKIP_NATIVE_UI=1 (e.g. CI without a desktop).
A window flashes on screen for ~2 s while this runs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("FMPRO_SKIP_NATIVE_UI") == "1",
    reason="needs a Windows desktop session",
)

PROBE = textwrap.dedent(r"""
    import ctypes, json, sys
    from ctypes import wintypes
    sys.path.insert(0, ROOT)
    import ui.qt_compat
    from PyQt6.QtCore import QPoint, QTimer
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from ui.theme import theme
    theme().install(app, mode="dark")
    from ui.main_window import MainWindow
    u = ctypes.windll.user32
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    w = MainWindow()
    w.closeEvent = lambda e: e.accept()          # don't persist geometry / stop workers
    w.showNormal(); w.resize(1000, 640); w.move(60, 60)
    out = {}

    def hit(widget, lx, ly):
        # Physical screen point of a widget-local logical point -> WM_NCHITTEST answer
        hwnd = wintypes.HWND(int(w.winId()))
        origin = wintypes.POINT(0, 0); u.ClientToScreen(hwnd, ctypes.byref(origin))
        p = widget.mapTo(w, QPoint(lx, ly)) if widget is not w else QPoint(lx, ly)
        dpr = w.devicePixelRatioF()
        x, y = origin.x + int(p.x() * dpr), origin.y + int(p.y() * dpr)
        return u.SendMessageW(hwnd, 0x84, 0, ((y & 0xFFFF) << 16) | (x & 0xFFFF))

    def normal():
        hwnd = wintypes.HWND(int(w.winId()))
        wr, cr = wintypes.RECT(), wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(wr)); u.GetClientRect(hwnd, ctypes.byref(cr))
        dpr = w.devicePixelRatioF()
        tab = w.workspace_tabs._buttons[0]
        out.update(
            chrome=w._chrome is not None,
            layered=bool(u.GetWindowLongW(hwnd, -20) & 0x80000),
            window=[wr.right - wr.left, wr.bottom - wr.top], client=[cr.right, cr.bottom],
            qt_physical=[round(w.width() * dpr), round(w.height() * dpr)],
            caption_w=w._chrome.caption_buttons_width() if w._chrome else 0,
            caption_space=w.title_bar.caption_space.width(),
            backdrop=w.property("backdrop"),
            hit_top_edge=hit(w, w.width() // 2, 1),
            hit_title_empty=hit(w.title_bar.drag_area, 10, 20),
            hit_tab=hit(tab, tab.width() // 2, tab.height() // 2),
            hit_new_tab=hit(w.workspace_tabs.btn_new_tab, 5, 5),
            hit_address_row=hit(w.toolbar, 60, w.toolbar.height() // 2),
            hit_left_edge=hit(w, 1, w.height() // 2),
        )
        w.showMaximized()
        QTimer.singleShot(800, maximized)

    def maximized():
        hwnd = wintypes.HWND(int(w.winId()))
        cr = wintypes.RECT(); u.GetClientRect(hwnd, ctypes.byref(cr))
        origin = wintypes.POINT(0, 0); u.ClientToScreen(hwnd, ctypes.byref(origin))
        class MI(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("f", wintypes.DWORD)]
        mi = MI(); mi.cb = ctypes.sizeof(MI)
        u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        out.update(
            max_client=[origin.x, origin.y, origin.x + cr.right, origin.y + cr.bottom],
            work_area=[mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom],
            max_hit_top=hit(w, w.width() // 2, 1),
        )
        print("RESULT " + json.dumps(out), flush=True)
        app.quit()

    QTimer.singleShot(1200, normal)
    app.exec()
""").replace("ROOT", repr(str(ROOT)))

HTCLIENT, HTCAPTION, HTLEFT, HTTOP = 1, 2, 10, 12


@pytest.fixture(scope="module")
def report():
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}   # real platform
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=90, env=env, cwd=str(ROOT))
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"probe failed (exit {proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return json.loads(line[len("RESULT "):])


def test_chrome_is_installed_without_layered_window(report):
    assert report["chrome"]
    assert report["layered"] is False, "WS_EX_LAYERED makes transparent chrome click-through and kills Mica"
    assert report["backdrop"] == "system"


def test_client_area_covers_whole_window_and_qt_agrees(report):
    assert report["client"] == report["window"], "native caption bar still reserved"
    qw, qh = report["qt_physical"]
    cw, ch = report["client"]
    assert abs(qw - cw) <= 2 and abs(qh - ch) <= 2, f"Qt thinks {qw}x{qh}, Windows says {cw}x{ch}"


def test_title_bar_hit_testing(report):
    assert report["hit_top_edge"] == HTTOP
    assert report["hit_left_edge"] == HTLEFT
    assert report["hit_title_empty"] == HTCAPTION      # drag / double-click maximize / Alt+Space
    assert report["hit_tab"] == HTCLIENT               # tabs stay clickable
    assert report["hit_new_tab"] == HTCLIENT
    assert report["hit_address_row"] == HTCLIENT


def test_space_reserved_for_dwm_caption_buttons(report):
    assert report["caption_w"] > 80
    assert report["caption_space"] == report["caption_w"]


def test_maximized_window_stays_inside_work_area(report):
    l, t, r, b = report["max_client"]
    wl, wt, wr, wb = report["work_area"]
    assert l >= wl and t >= wt and r <= wr and b <= wb, f"client {report['max_client']} overhangs {report['work_area']}"
    assert report["max_hit_top"] != HTTOP, "no resize border when maximized"

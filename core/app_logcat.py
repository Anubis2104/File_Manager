"""
core/app_logcat.py
Comprehensive UI & Core Processing Diagnostic Logger (Logcat for Desktop Qt).
Features:
  - Real-time logging of all UI events (clicks, shortcuts, navigation, dialogs, context menus).
  - Background processing tracking (workers, ExifTool CLI calls, PIL/rawpy/OpenCV decode).
  - Main Thread Block / UI Freezing Watchdog detection (ANR warning).
  - Qt internal message hook (qInstallMessageHandler).
  - Unhandled exception hook (sys.excepthook).
  - Dual output: Rotating log file in logs/ + In-memory RingBuffer + Console.
  - Signal-ready for Live In-App Logcat Viewer (F12).
"""
from __future__ import annotations

import os
import sys
import time
import threading
import traceback
import atexit
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Any, Callable

from PyQt6.QtCore import (
    Qt, QObject, QEvent, pyqtSignal, QTimer, QThread,
    qInstallMessageHandler, QtMsgType
)

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton,
    QLineEdit, QMenu, QDialog, QAbstractItemView
)



class LogLevel(IntEnum):
    VERBOSE = 1
    DEBUG   = 2
    INFO    = 3
    WARN    = 4
    ERROR   = 5
    FATAL   = 6

    @property
    def short_name(self) -> str:
        return {1: "V", 2: "D", 3: "I", 4: "W", 5: "E", 6: "F"}[self.value]

    @property
    def color_ansi(self) -> str:
        return {
            1: "\033[90m", # Gray
            2: "\033[36m", # Cyan
            3: "\033[32m", # Green
            4: "\033[33m", # Yellow
            5: "\033[31m", # Red
            6: "\033[35;1m" # Bright Magenta
        }[self.value]


try:
    _HOME_PATH = Path.home()
    _HOME_STR_BS = str(_HOME_PATH)
    _HOME_STR_FS = _HOME_STR_BS.replace("\\", "/")
except Exception:
    _HOME_STR_BS = ""
    _HOME_STR_FS = ""


def mask_personal_info(text: Any) -> str:
    r"""
    Sanitizes personal user paths and usernames from log messages.
    Replaces user home directory (e.g. C:\Users\Username or /home/username) with '~'.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    if not text:
        return ""
    if _HOME_STR_BS and _HOME_STR_BS in text:
        text = text.replace(_HOME_STR_BS, "~")
    if _HOME_STR_FS and _HOME_STR_FS in text:
        text = text.replace(_HOME_STR_FS, "~")
    return text


def _get_widget_text(widget: QObject) -> str:
    """Safely extract display text from any Qt widget without crashing."""
    try:
        t = getattr(widget, "text", None)
        if callable(t):
            return str(t())
        elif isinstance(t, str):
            return t
    except Exception:
        pass
    return ""


@dataclass
class LogRecord:
    timestamp: datetime
    level: LogLevel
    tag: str
    thread_name: str
    is_main_thread: bool
    message: str
    extra: dict = field(default_factory=dict)

    def formatted_text(self) -> str:
        t_str = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        thread_label = "Main" if self.is_main_thread else self.thread_name
        sanitized_msg = mask_personal_info(self.message)
        return f"{t_str} [{self.level.short_name}] [{thread_label:^8}] [{self.tag:<16}] {sanitized_msg}"


class UIEventFilter(QObject):
    """
    Transparent application-wide event filter that captures:
    - Button clicks & ToolButton triggers
    - Mouse presses (Left, Right / Context Menu)
    - Keyboard inputs & Shortcuts
    - Window & Dialog lifecycle (Show, Close)
    """

    def __init__(self, logcat: "AppLogcat", parent=None):
        super().__init__(parent)
        self.logcat = logcat

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            etype = event.type()

            # ── Mouse clicks ──
            if etype == QEvent.Type.MouseButtonPress:
                btn_type = "LEFT" if event.button() == Qt.MouseButton.LeftButton else (
                    "RIGHT" if event.button() == Qt.MouseButton.RightButton else str(event.button())
                )
                w_name = watched.objectName() or watched.__class__.__name__
                text = _get_widget_text(watched)
                if text:
                    msg = f"MousePress ({btn_type}) on <{w_name}> '{text}'"
                else:
                    msg = f"MousePress ({btn_type}) on <{w_name}>"
                
                tag = "UI:ContextMenu" if btn_type == "RIGHT" else "UI:Click"
                self.logcat.log(LogLevel.DEBUG, tag, msg)

            # ── Keyboard presses ──
            elif etype == QEvent.Type.KeyPress:
                key = event.key()
                modifiers = []
                mods = event.modifiers()
                if mods & Qt.KeyboardModifier.ControlModifier:
                    modifiers.append("Ctrl")
                if mods & Qt.KeyboardModifier.AltModifier:
                    modifiers.append("Alt")
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    modifiers.append("Shift")
                
                key_text = event.text()
                # Map special keys
                special_keys = {
                    Qt.Key.Key_F5: "F5",
                    Qt.Key.Key_F12: "F12",
                    Qt.Key.Key_Return: "Enter",
                    Qt.Key.Key_Enter: "Enter",
                    Qt.Key.Key_Escape: "Esc",
                    Qt.Key.Key_Left: "Left",
                    Qt.Key.Key_Right: "Right",
                    Qt.Key.Key_Up: "Up",
                    Qt.Key.Key_Down: "Down",
                    Qt.Key.Key_Delete: "Delete",
                    Qt.Key.Key_Backspace: "Backspace",
                }
                name = special_keys.get(key, key_text if (key_text and key_text.isprintable()) else hex(key))
                combo = "+".join(modifiers + [name]) if modifiers else name
                
                w_name = watched.objectName() or watched.__class__.__name__
                self.logcat.log(LogLevel.VERBOSE, "UI:Keyboard", f"Key [{combo}] focused on <{w_name}>")

            # ── Dialog/Window lifecycle ──
            elif etype == QEvent.Type.Show:
                if isinstance(watched, (QDialog, QWidget)) and watched.isWindow():
                    title = getattr(watched, "windowTitle", lambda: "")() or watched.__class__.__name__
                    self.logcat.log(LogLevel.INFO, "UI:Window", f"Window Opened: [{title}]")
            elif etype == QEvent.Type.Close:
                if isinstance(watched, (QDialog, QWidget)) and watched.isWindow():
                    title = getattr(watched, "windowTitle", lambda: "")() or watched.__class__.__name__
                    self.logcat.log(LogLevel.INFO, "UI:Window", f"Window Closed: [{title}]")
        except Exception:
            pass

        return super().eventFilter(watched, event)



class UIWatchdogTimer(QObject):
    """
    Heartbeat watchdog running on a secondary thread to detect Main Thread freezes.
    If the Qt Event Loop is blocked for > 200ms, it records an ANR (Application Not Responding) warning.
    """
    def __init__(self, logcat: "AppLogcat", parent=None):
        super().__init__(parent)
        self.logcat = logcat
        self._main_heartbeat = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def tick(self):
        """Called every 50ms from Qt Main Thread event loop."""
        self._main_heartbeat = time.time()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="WatchdogThread")
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            time.sleep(0.1)
            lag = time.time() - self._main_heartbeat
            if lag > 0.25: # More than 250ms freeze
                self.logcat.log(
                    LogLevel.WARN,
                    "PERF:MainLag",
                    f"Main GUI Thread blocked for {lag*1000:.0f} ms! (Potential GUI Freeze)"
                )
                # Avoid spamming every 100ms for the same long block
                time.sleep(0.5)


class AppLogcat(QObject):
    """
    Central Diagnostic & Event Logger.
    Accessible globally via `AppLogcat.instance()`.
    """
    new_log_record = pyqtSignal(object)  # Emits LogRecord to UI listeners

    _instance: Optional["AppLogcat"] = None

    MAX_MEMORY_LOGS = 3000

    def __init__(self, log_dir: Optional[Path] = None):
        super().__init__()
        if log_dir is not None:
            self.log_dir = log_dir
        else:
            try:
                from utils.file_utils import get_app_dir
                self.log_dir = get_app_dir() / "logs"
            except Exception:
                self.log_dir = Path(__file__).parent.parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._prune_old_logs(max_logs=20)
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = self.log_dir / f"fmpro_debug_{timestamp_str}.log"
        self._file_handle = open(self.log_file_path, "a", encoding="utf-8", buffering=1)

        self._ring_buffer: deque[LogRecord] = deque(maxlen=self.MAX_MEMORY_LOGS)
        self._lock = threading.Lock()
        self._event_filter: Optional[UIEventFilter] = None
        self._watchdog: Optional[UIWatchdogTimer] = None
        self._main_timer: Optional[QTimer] = None

    @classmethod
    def instance(cls) -> "AppLogcat":
        if cls._instance is None:
            cls._instance = AppLogcat()
        return cls._instance

    def install(self, app: QApplication):
        """Install global event filter, exception handler, and Qt message handler."""
        # 1. UI Event Filter
        self._event_filter = UIEventFilter(self)
        app.installEventFilter(self._event_filter)

        # 2. Qt Message Handler
        def qt_message_handler(mode: QtMsgType, context, message: str):
            level_map = {
                QtMsgType.QtDebugMsg: LogLevel.DEBUG,
                QtMsgType.QtInfoMsg: LogLevel.INFO,
                QtMsgType.QtWarningMsg: LogLevel.WARN,
                QtMsgType.QtCriticalMsg: LogLevel.ERROR,
                QtMsgType.QtFatalMsg: LogLevel.FATAL,
            }
            lvl = level_map.get(mode, LogLevel.INFO)
            self.log(lvl, "SYS:Qt", message)

        qInstallMessageHandler(qt_message_handler)

        # 3. Python sys.excepthook
        old_excepthook = sys.excepthook
        def custom_excepthook(exc_type, exc_value, exc_traceback):
            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.log(LogLevel.FATAL, "SYS:Crash", f"Unhandled Exception:\n{tb_str}")
            old_excepthook(exc_type, exc_value, exc_traceback)

        sys.excepthook = custom_excepthook

        # 4. Main Thread Watchdog
        self._watchdog = UIWatchdogTimer(self)
        self._watchdog.start()

        self._main_timer = QTimer(self)
        self._main_timer.setInterval(50)
        self._main_timer.timeout.connect(self._watchdog.tick)
        self._main_timer.start()

        app.aboutToQuit.connect(self.shutdown)
        self.log(LogLevel.INFO, "SYS:Init", f"AppLogcat initialized. Logging to: {self.log_file_path}")

    def log(self, level: LogLevel, tag: str, message: str, **extra):
        """Record a diagnostic event."""
        now = datetime.now()
        cur_thread = threading.current_thread()
        is_main = isinstance(cur_thread, threading._MainThread) if hasattr(threading, "_MainThread") else (cur_thread.name == "MainThread")
        thread_name = cur_thread.name or f"Thread-{threading.get_ident()}"

        record = LogRecord(
            timestamp=now,
            level=level,
            tag=tag,
            thread_name=thread_name,
            is_main_thread=is_main,
            message=mask_personal_info(message),
            extra=extra
        )

        formatted = record.formatted_text()

        # 1. Console stream with ANSI
        try:
            ansi_color = level.color_ansi
            ansi_reset = "\033[0m"
            print(f"{ansi_color}{formatted}{ansi_reset}", flush=True)
        except Exception:
            pass

        # 2. File output
        with self._lock:
            try:
                self._file_handle.write(formatted + "\n")
                self._file_handle.flush()
            except Exception:
                pass
            self._ring_buffer.append(record)

        # 3. Qt Signal for GUI listeners
        try:
            self.new_log_record.emit(record)
        except Exception:
            pass

    # Convenience shortcuts
    def v(self, tag: str, message: str, **kwargs):
        self.log(LogLevel.VERBOSE, tag, message, **kwargs)

    def d(self, tag: str, message: str, **kwargs):
        self.log(LogLevel.DEBUG, tag, message, **kwargs)

    def i(self, tag: str, message: str, **kwargs):
        self.log(LogLevel.INFO, tag, message, **kwargs)

    def w(self, tag: str, message: str, **kwargs):
        self.log(LogLevel.WARN, tag, message, **kwargs)

    def e(self, tag: str, message: str, **kwargs):
        self.log(LogLevel.ERROR, tag, message, **kwargs)

    def perf(self, action_name: str, duration_ms: float, details: str = ""):
        msg = f"{action_name} executed in {duration_ms:.2f} ms"
        if details:
            msg += f" ({details})"
        lvl = LogLevel.WARN if duration_ms > 300 else LogLevel.INFO
        self.log(lvl, "PERF:Latency", msg)

    def get_recent_records(self) -> list[LogRecord]:
        with self._lock:
            return list(self._ring_buffer)

    def _prune_old_logs(self, max_logs: int = 20):
        """Keep only the most recent N log files in logs/ to prevent unbounded accumulation."""
        try:
            log_files = sorted(self.log_dir.glob("fmpro_debug_*.log"), key=lambda f: f.stat().st_mtime)
            while len(log_files) > max_logs:
                oldest = log_files.pop(0)
                try:
                    oldest.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def shutdown(self):
        """Cleanly stop background watchdog thread, timers, and flush/close file handle."""
        try:
            if self._main_timer:
                self._main_timer.stop()
        except (RuntimeError, Exception):
            pass
        try:
            if self._watchdog:
                self._watchdog.stop()
        except (RuntimeError, Exception):
            pass
        with self._lock:
            if hasattr(self, "_file_handle") and self._file_handle and not self._file_handle.closed:
                try:
                    self._file_handle.flush()
                    self._file_handle.close()
                except Exception:
                    pass

    def clear(self):
        with self._lock:
            self._ring_buffer.clear()


# Global quick helper
logcat = AppLogcat.instance()
atexit.register(logcat.shutdown)

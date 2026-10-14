"""
utils/safe_log.py
Never-raising bridge to the global logcat for core / utils / duplicate modules.

core.app_logcat is imported lazily on each call (as the inline blocks it replaces did):
importing it creates the log file and pulls in Qt, which these modules avoid at import time.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def safe_log(level: str, tag: str, message: str) -> None:
    """Log via logcat.<level>() ('d', 'i', 'w', 'e'). Logging failures are ignored."""
    try:
        from core.app_logcat import logcat
        getattr(logcat, level)(tag, message)
    except Exception:
        pass


def _caller_location(depth: int) -> str:
    """'core/metadata.py:106' for the frame `depth` levels above this function."""
    frame = sys._getframe(depth + 1)
    path = Path(frame.f_code.co_filename)
    try:
        rel = path.resolve().relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        rel = path.name
    return f"{rel}:{frame.f_lineno}"


def log_swallowed(tag: str, exc: BaseException, label: str = "Loi im lang") -> None:
    """
    Record an exception that is intentionally swallowed, tagged with the caller's
    real file:line (replaces hand-written, drifting '[file.py:123]' markers).
    """
    try:
        location = _caller_location(1)
    except Exception:
        location = "?"
    safe_log("w", tag, f"{label} [{location}]: {exc}")

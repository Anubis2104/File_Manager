"""
tests/test_safe_log.py
Characterization tests for utils.safe_log — the helper that replaces the inline
`try: from core.app_logcat import logcat; logcat.w(...) except Exception: pass` blocks.
"""
from __future__ import annotations

import sys
import types

import pytest

from utils import safe_log as sl


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def __getattr__(self, level):
        return lambda tag, msg: self.calls.append((level, tag, msg))


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    fake = types.ModuleType("core.app_logcat")
    fake.logcat = rec
    monkeypatch.setitem(sys.modules, "core.app_logcat", fake)
    return rec


def test_log_swallowed_reports_real_caller_location(recorder):
    try:
        raise OSError("disk gone")
    except OSError as exc:
        expected_line = sys._getframe().f_lineno + 1
        sl.log_swallowed("METADATA", exc)

    assert recorder.calls == [
        ("w", "METADATA", f"Loi im lang [tests/test_safe_log.py:{expected_line}]: disk gone"),
    ]


def test_log_swallowed_keeps_custom_label(recorder):
    sl.log_swallowed("WORKERS", ValueError("bad"), label="Bỏ qua lỗi")
    level, tag, msg = recorder.calls[0]
    assert (level, tag) == ("w", "WORKERS")
    assert msg.startswith("Bỏ qua lỗi [tests/test_safe_log.py:") and msg.endswith("]: bad")


def test_safe_log_dispatches_level(recorder):
    sl.safe_log("d", "ExifToolDaemon", "24 tags")
    assert recorder.calls == [("d", "ExifToolDaemon", "24 tags")]


def test_helpers_never_raise_when_logcat_is_broken(monkeypatch):
    broken = types.ModuleType("core.app_logcat")   # no `logcat` attribute → ImportError
    monkeypatch.setitem(sys.modules, "core.app_logcat", broken)
    sl.safe_log("w", "TAG", "msg")
    sl.log_swallowed("TAG", RuntimeError("x"))


def test_helpers_never_raise_when_logcat_call_fails(monkeypatch):
    class Exploding:
        def w(self, *a):
            raise RuntimeError("log file closed")
    fake = types.ModuleType("core.app_logcat")
    fake.logcat = Exploding()
    monkeypatch.setitem(sys.modules, "core.app_logcat", fake)
    sl.log_swallowed("TAG", RuntimeError("x"))

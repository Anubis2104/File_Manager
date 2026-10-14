"""
tests/test_exiftool_daemon.py
ExifToolDaemon: a hung ExifTool must not hang the caller (timeout used to be ignored
because stdout.readline() blocks), and the real fast path must keep working.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from core.metadata import ExifToolDaemon

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_EXIFTOOL = PROJECT_ROOT / "ExifTool.exe"

HANG_SCRIPT = """\
import sys
# Accept commands but never print the {ready} sentinel (simulates a hung ExifTool).
for _line in sys.stdin:
    pass
"""


@pytest.fixture
def hung_exiftool(tmp_path) -> str:
    script = tmp_path / "hang.py"
    script.write_text(HANG_SCRIPT, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "fake_exiftool.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "fake_exiftool"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return str(launcher)


def _run_with_watchdog(fn, limit: float):
    """Run fn in a thread; return (finished, result, elapsed) without hanging the test run."""
    box = {}
    t0 = time.monotonic()
    th = threading.Thread(target=lambda: box.setdefault("r", fn()), daemon=True)
    th.start()
    th.join(limit)
    return not th.is_alive(), box.get("r"), time.monotonic() - t0


def test_execute_times_out_on_hung_exiftool(hung_exiftool):
    daemon = ExifToolDaemon(hung_exiftool, timeout=1.0)
    try:
        assert daemon.start()
        finished, result, elapsed = _run_with_watchdog(lambda: daemon._execute(["-ver"]), limit=10)

        assert finished, "_execute() blocked past its timeout (readline never returns)"
        assert result == ""
        assert elapsed < 6, f"timeout=1.0 but took {elapsed:.1f}s"
        assert not daemon.is_running(), "hung daemon must be stopped so the next call restarts it"
    finally:
        daemon.close()


def test_concurrent_callers_survive_timeout_restart(hung_exiftool, monkeypatch):
    """Shared daemon (scanner workers): a kill by one thread must not crash the others."""
    import core.metadata as md

    logged: list[str] = []
    monkeypatch.setattr(md, "safe_log", lambda lvl, tag, msg: logged.append(msg))
    daemon = ExifToolDaemon(hung_exiftool, timeout=1.0)
    results: list[str] = []
    try:
        threads = [threading.Thread(target=lambda: results.append(daemon._execute(["-ver"])))
                   for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)

        assert not any(t.is_alive() for t in threads), "a caller hung"
        assert results == ["", "", ""]
        assert not [m for m in logged if "Loi giao tiep" in m], logged
        assert sum("Timeout" in m for m in logged) == 3
    finally:
        daemon.close()


def test_read_json_returns_empty_dict_on_timeout(hung_exiftool, tmp_path):
    """read_all() falls back to subprocess when the daemon returns {}."""
    daemon = ExifToolDaemon(hung_exiftool, timeout=1.0)
    try:
        finished, result, _ = _run_with_watchdog(lambda: daemon.read_json(tmp_path / "x.jpg"), limit=10)
        assert finished and result == {}
    finally:
        daemon.close()


@pytest.mark.skipif(not REAL_EXIFTOOL.exists(), reason="bundled ExifTool.exe not present")
def test_real_exiftool_daemon_reads_unicode_filename(tmp_path):
    from PIL import Image

    img = tmp_path / "Ảnh_Đà_Lạt_中.jpg"
    Image.new("RGB", (32, 16), "red").save(img)

    with ExifToolDaemon(str(REAL_EXIFTOOL), timeout=30) as et:
        first = et.read_json(img)
        second = et.read_json(img)   # same process, served from the warm daemon

    for data in (first, second):
        assert data.get("File:FileName") == img.name
        assert data.get("File:ImageWidth") == 32


def _pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(wintypes.HANDLE(h), ctypes.byref(code))
        return code.value == 259                       # STILL_ACTIVE
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


@pytest.mark.skipif(sys.platform != "win32" or not REAL_EXIFTOOL.exists(), reason="Windows + bundled ExifTool.exe")
@pytest.mark.parametrize("exit_how", ["normal", "hard"])
def test_daemon_process_does_not_outlive_python(tmp_path, exit_how):
    """The shared stay_open daemon used to survive the app: one orphan ExifTool.exe per run."""
    import subprocess
    import textwrap
    from PIL import Image

    img = tmp_path / "x.jpg"
    Image.new("RGB", (8, 8)).save(img)
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(PROJECT_ROOT)!r})
        from pathlib import Path
        from core.metadata import _get_global_daemon
        d = _get_global_daemon({str(REAL_EXIFTOOL)!r})
        assert d.read_json(Path({str(img)!r}))
        print("PID", d._proc.pid, flush=True)
        if {exit_how!r} == "hard":
            os._exit(0)        # no atexit, no finalizers: like a crash
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("PID ")), None)
    assert line, proc.stderr[-1500:]
    pid = int(line.split()[1])

    deadline = time.monotonic() + 5
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    alive = _pid_alive(pid)
    if alive:                                          # never leave the orphan behind
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    assert not alive, f"ExifTool daemon (pid {pid}) outlived its Python process ({exit_how} exit)"


def test_resolve_exiftool_falls_back_to_path_lookup(monkeypatch):
    """No candidate binary works → must consult PATH, not crash with NameError (missing import)."""
    import utils.date_utils as du

    monkeypatch.setattr(du, "_test_exiftool_binary", lambda exe: False)
    result = du.resolve_exiftool_exe("exiftool")
    assert isinstance(result, str) and result

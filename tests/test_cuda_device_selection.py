"""
CUDA detection and device wiring for duplicate detection.

- get_cuda_info() must say WHY it fell back to CPU (CPU-only torch build vs
  driver/GPU problem vs torch missing) instead of silently reporting "CPU".
- performance.use_cuda=false must reach the pHash and DINOv2 engines.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from utils import cuda_helper


@pytest.fixture(autouse=True)
def _fresh_cuda_cache():
    cuda_helper.reset_cache()
    yield
    cuda_helper.reset_cache()


def _fake_torch(cuda_build: str | None, available: bool) -> types.ModuleType:
    torch = types.ModuleType("torch")
    torch.__version__ = "9.9.9+fake"
    torch.version = types.SimpleNamespace(cuda=cuda_build)
    torch.cuda = types.SimpleNamespace(is_available=lambda: available)
    return torch


def test_cpu_only_torch_build_is_reported_as_reason(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_build=None, available=False))

    info = cuda_helper.get_cuda_info()

    assert not info.available
    assert "CPU-only" in info.reason
    assert info.reason in str(info)


def test_cuda_build_without_usable_gpu_points_at_driver(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_build="12.6", available=False))

    info = cuda_helper.get_cuda_info()

    assert not info.available
    assert "12.6" in info.reason
    assert "driver" in info.reason.lower()


def test_missing_torch_is_reported_as_reason(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise ImportError

    info = cuda_helper.get_cuda_info()

    assert not info.available
    assert "not installed" in info.reason


def test_dup_manager_passes_device_to_both_engines(monkeypatch):
    import duplicate.dup_manager as dm
    import duplicate.phash_engine as pe
    import duplicate.embedding_engine as ee

    seen: dict[str, str] = {}

    class FakePHash:
        def __init__(self, device="cuda"):
            seen["phash"] = device

        def compute_batch(self, paths, **_kw):
            return {}

        def find_duplicate_groups(self, hashes, **_kw):
            return []

    class FakeEmbed:
        def __init__(self, model_name="", device="cuda", batch_size=32):
            seen["embed"] = device

        def build_index(self, paths, **_kw):
            pass

        def find_all_duplicates(self, threshold):
            return []

    monkeypatch.setattr(pe, "PHashEngine", FakePHash)
    monkeypatch.setattr(ee, "EmbeddingEngine", FakeEmbed)

    mgr = dm.DupManager(device="cpu")
    mgr.find_duplicates_phash([Path("a.jpg")])
    mgr.find_duplicates_embedding([Path("a.jpg")])

    assert seen == {"phash": "cpu", "embed": "cpu"}


def test_dup_scan_worker_forwards_device_to_manager(monkeypatch):
    import duplicate.dup_manager as dm
    from core.workers import DupScanWorker

    captured: dict[str, str] = {}

    class FakeManager:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def find_duplicates_phash(self, *_a, **_kw):
            return []

    monkeypatch.setattr(dm, "DupManager", FakeManager)

    worker = DupScanWorker([Path("a.jpg")], engine_mode="phash", device="cpu")
    worker.run()

    assert captured.get("device") == "cpu"


# ─── Startup: CUDA probe must not block the GUI thread ───

def _qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_probes_cuda_off_the_gui_thread(monkeypatch, tmp_path):
    import threading
    from PyQt6.QtTest import QTest
    import ui.dialogs.settings_dialog as sd

    app = _qapp()
    monkeypatch.setattr(sd, "SETTINGS_PATH", tmp_path / "settings.json")
    callers: list[threading.Thread] = []
    fake = cuda_helper.CudaInfo(
        available=True, device_id=0, device_name="Fake RTX", total_memory_gb=6.0,
        compute_capability=(8, 9), torch_version="9.9.9", cuda_version="12.6",
    )

    def slow_probe(device_id: int = 0):
        import time
        callers.append(threading.current_thread())
        time.sleep(0.05)                     # stands in for `import torch` + CUDA init
        return fake

    monkeypatch.setattr(cuda_helper, "get_cuda_info", slow_probe)

    from ui.main_window import MainWindow
    win = MainWindow()
    try:
        badge = win.app_statusbar.lbl_cuda
        for _ in range(250):
            if badge.text() == "GPU: Fake RTX":
                break
            QTest.qWait(20)

        assert callers, "CUDA was never probed"
        assert all(t is not threading.main_thread() for t in callers)
        assert badge.text() == "GPU: Fake RTX"
    finally:
        win.close()
        win.deleteLater()


def test_status_bar_shows_pending_badge_until_probe_finishes():
    _qapp()
    from ui.widgets.statusbar import AppStatusBar

    bar = AppStatusBar()
    bar.set_cuda_pending()
    assert bar.lbl_cuda.text() == "GPU…"

    bar.set_cuda_info("CUDA: Not available (using CPU) — PyTorch 9.9 is a CPU-only build")
    assert bar.lbl_cuda.text() == "CPU"
    assert "CPU-only build" in bar.lbl_cuda.toolTip()


def test_closing_window_while_cuda_probe_runs_does_not_crash():
    """The probe outlives a window closed during startup (torch import takes seconds).
    Subprocess: destroying a running QThread aborts the whole process."""
    import subprocess
    import textwrap

    root = Path(__file__).resolve().parent.parent
    script = textwrap.dedent(f"""
        import os, sys, time
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.path.insert(0, {str(root)!r})
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        from utils import cuda_helper
        real = cuda_helper.get_cuda_info
        def slow(device_id=0):
            time.sleep(3.0)                 # longer than closeEvent's 2 s thread wait
            return cuda_helper.CudaInfo(False, -1, "CPU", 0.0, (0, 0), "x", "N/A", reason="test")
        cuda_helper.get_cuda_info = slow
        from ui.main_window import MainWindow
        w = MainWindow(); w.show(); app.processEvents()
        w.close(); w.deleteLater(); del w
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        t0 = time.time()
        while time.time() - t0 < 3.0:      # let the probe finish and emit into the void
            app.processEvents(); time.sleep(0.02)
        print("SURVIVED", flush=True)
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, cwd=str(root))
    assert proc.returncode == 0 and "SURVIVED" in proc.stdout, proc.stderr[-1500:]

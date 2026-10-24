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

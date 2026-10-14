"""
tests/test_defect_regressions.py
Regression tests for verified defects (orch-fix-defect, 2026-10-14).

Each test reproduces a real bug on the real filesystem:
  #1 Rename log recorded the NEW path as src_path → undo was a silent no-op.
  #2 QueueDockWidget built RenameLogger() without a log path → TypeError.
  #3 Partial MD5 at log time vs full MD5 at restore → files > 64 MB never restored.
  #4 Inspector trim/repair destroyed bytes with no way to recover them.
  #5 ensure_writable() wiped Hidden/System attributes on every rename.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from core.inspector import inspect_file, repair_jpeg_header, trim_file_overlay
from core.logger import RenameLogger
from utils.file_utils import RenameOperation, safe_rename_with_retry


VALID_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
    b"\xff\xd9"
)


def _read_log(log_path: Path) -> list[dict]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ─────────────────────────────────────────────
# #1 — Undo must restore the original name
# ─────────────────────────────────────────────

def test_rename_log_records_original_path(tmp_path):
    src = tmp_path / "IMG_0001.jpg"
    dst = tmp_path / "Camera_141026_H_19201080.jpg"
    src.write_bytes(b"photo-bytes")

    op = RenameOperation(src=src, dst=dst, dry_run=False)
    assert op.execute()

    log_path = tmp_path / "rename_log.jsonl"
    RenameLogger(log_path).log_rename_op(op)

    record = _read_log(log_path)[0]
    assert record["src_path"] == str(src)
    assert record["dst_path"] == str(dst)
    assert record["src_name"] == "IMG_0001.jpg"


def test_restore_returns_file_to_original_name(tmp_path):
    originals = [tmp_path / f"orig_{i}.jpg" for i in range(3)]
    for i, p in enumerate(originals):
        p.write_bytes(f"content-{i}".encode())

    ops = [RenameOperation(src=p, dst=tmp_path / f"renamed_{i}.jpg", dry_run=False)
           for i, p in enumerate(originals)]
    logger = RenameLogger(tmp_path / "rename_log.jsonl")
    for op in ops:
        assert op.execute()
        logger.log_rename_op(op)

    results = logger.restore_from_log(verify_checksum=True)

    assert all(r["success"] for r in results), [r["error"] for r in results]
    for i, p in enumerate(originals):
        assert p.exists(), f"{p.name} was not restored"
        assert p.read_bytes() == f"content-{i}".encode()
        assert not (tmp_path / f"renamed_{i}.jpg").exists()


def test_rename_worker_log_is_restorable(tmp_path):
    """Full UI-path flow: RenameWorker executes + logs, restore brings names back."""
    from core.workers import RenameWorker

    src = tmp_path / "DSC_9999.jpg"
    src.write_bytes(b"worker-bytes")
    dst = tmp_path / "001_DSC_9999.jpg"
    log_path = tmp_path / "rename_log.jsonl"

    worker = RenameWorker(ops=[RenameOperation(src=src, dst=dst, dry_run=False)],
                          logger=RenameLogger(log_path))
    worker.run()
    assert dst.exists() and not src.exists()

    results = RenameLogger(log_path).restore_from_log()
    assert results and results[0]["success"], results
    assert src.exists() and not dst.exists()


def test_restore_rejects_legacy_entry_without_original_name(tmp_path):
    """Logs written before the fix have src_path == dst_path: report failure, never fake success."""
    f = tmp_path / "already_renamed.jpg"
    f.write_bytes(b"x")
    log_path = tmp_path / "rename_log.jsonl"
    log_path.write_text(json.dumps({
        "version": "1.0", "timestamp": "2026-10-04T04:12:00", "operation": "rename",
        "src_path": str(f), "dst_path": str(f), "src_name": f.name, "dst_name": f.name,
        "checksum_before": "", "checksum_after": "", "error": "",
    }) + "\n", encoding="utf-8")

    results = RenameLogger(log_path).restore_from_log()

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["error"]
    assert f.exists()


# ─────────────────────────────────────────────
# #3 — Large files must pass checksum verification
# ─────────────────────────────────────────────

def test_restore_large_file_with_checksum(tmp_path):
    src = tmp_path / "clip.mp4"
    with open(src, "wb") as fh:
        fh.write(os.urandom(70 * 1024 * 1024))   # > 64 MB partial-hash threshold
    dst = tmp_path / "Trip_141026_H_38402160.mp4"

    op = RenameOperation(src=src, dst=dst, dry_run=False)
    assert op.execute()
    logger = RenameLogger(tmp_path / "rename_log.jsonl", compute_checksums=True)
    logger.log_rename_op(op)

    results = logger.restore_from_log(verify_checksum=True)

    assert results[0]["success"], results[0]["error"]
    assert src.exists()


def test_restore_still_detects_modified_file(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"original")
    dst = tmp_path / "b.jpg"
    op = RenameOperation(src=src, dst=dst, dry_run=False)
    assert op.execute()
    logger = RenameLogger(tmp_path / "rename_log.jsonl", compute_checksums=True)
    logger.log_rename_op(op)

    dst.write_bytes(b"tampered")
    results = logger.restore_from_log(verify_checksum=True)

    assert results[0]["success"] is False
    assert "Checksum" in results[0]["error"]
    assert dst.exists()


def test_restore_continues_when_one_checksum_read_fails(tmp_path, monkeypatch):
    """Gate 2 finding: an unreadable file must fail only its own entry, not abort the batch."""
    logger = RenameLogger(tmp_path / "rename_log.jsonl", compute_checksums=True)
    srcs = [tmp_path / "keep_a.jpg", tmp_path / "locked_b.jpg"]
    for p in srcs:
        p.write_bytes(p.name.encode())
        op = RenameOperation(src=p, dst=tmp_path / f"new_{p.name}", dry_run=False)
        assert op.execute()
        logger.log_rename_op(op)

    real = RenameLogger._log_checksum
    def flaky(path):
        if path.name == "new_locked_b.jpg":
            raise PermissionError("file is locked by another process")
        return real(path)
    monkeypatch.setattr(RenameLogger, "_log_checksum", staticmethod(flaky))

    results = logger.restore_from_log(verify_checksum=True)

    by_name = {Path(r["entry"].src_path).name: r for r in results}
    assert by_name["keep_a.jpg"]["success"] and srcs[0].exists()
    assert by_name["locked_b.jpg"]["success"] is False
    assert "Cannot verify checksum" in by_name["locked_b.jpg"]["error"]


# ─────────────────────────────────────────────
# #2 — Queue rename in the right dock must not crash
# ─────────────────────────────────────────────

def test_queue_dock_execute_rename_writes_restorable_log(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtTest import QTest
    from core.scanner import DirectoryScanner
    import ui.panels.right_dock_panel as rdp

    app = QApplication.instance() or QApplication(sys.argv)
    monkeypatch.chdir(tmp_path)   # relative rename_log.jsonl must land in tmp, not the repo
    monkeypatch.setattr(rdp.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(rdp.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(rdp.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(rdp.QMessageBox, "critical", staticmethod(lambda *a, **k: None))

    f = tmp_path / "queue_me.txt"
    f.write_bytes(b"q")
    info = DirectoryScanner(root=tmp_path, recursive=False).scan_file(f)

    dock = rdp.QueueDockWidget()
    dock.queue_items = [info]
    dock._execute_rename()   # raised TypeError before the fix

    renamed = tmp_path / "001_queue_me.txt"
    for _ in range(100):
        if renamed.exists() and not (dock._thread and dock._thread.isRunning()):
            break
        QTest.qWait(50)
    assert renamed.exists()

    results = RenameLogger(tmp_path / "rename_log.jsonl").restore_from_log()
    assert results and results[0]["success"], results
    assert f.exists()
    app.processEvents()


# ─────────────────────────────────────────────
# #4 — Inspector must keep removed bytes recoverable
# ─────────────────────────────────────────────

def test_trim_overlay_preserves_removed_bytes(tmp_path):
    overlay = b"PK\x03\x04" + os.urandom(2048)
    fp = tmp_path / "photo.jpg"
    original = VALID_JPEG + overlay
    fp.write_bytes(original)
    backup_dir = tmp_path / "_Quarantine"

    insp = inspect_file(fp)
    assert insp["status"] == "OVERLAY"
    ok, cut, msg = trim_file_overlay(fp, insp["valid_end_pos"], backup_dir=backup_dir)

    assert ok and cut == len(overlay)
    assert fp.read_bytes() == VALID_JPEG
    backups = list(backup_dir.glob("photo.jpg*.quarantined"))
    assert len(backups) == 1, list(backup_dir.iterdir()) if backup_dir.exists() else "no backup dir"
    assert fp.read_bytes() + backups[0].read_bytes() == original


def test_trim_keeps_backup_and_reports_success_when_utime_fails(tmp_path, monkeypatch):
    """Gate 2 finding: a timestamp failure after truncation must not discard the only backup."""
    import core.inspector as insp_mod

    overlay = b"Rar!" + os.urandom(512)
    fp = tmp_path / "pic.jpg"
    fp.write_bytes(VALID_JPEG + overlay)
    backup_dir = tmp_path / "_Quarantine"

    def no_utime(*a, **k):
        raise PermissionError("utime denied")
    monkeypatch.setattr(insp_mod.os, "utime", no_utime)

    ok, cut, msg = trim_file_overlay(fp, len(VALID_JPEG), backup_dir=backup_dir)

    assert ok and cut == len(overlay)
    assert fp.read_bytes() == VALID_JPEG
    backups = list(backup_dir.glob("pic.jpg*.quarantined"))
    assert len(backups) == 1 and backups[0].read_bytes() == overlay


def test_repair_jpeg_header_preserves_removed_prefix(tmp_path):
    prefix = b"\x00GARBAGE-PREFIX\x00" * 8
    fp = tmp_path / "broken.jpg"
    original = prefix + VALID_JPEG
    fp.write_bytes(original)
    backup_dir = tmp_path / "_Quarantine"

    ok, msg = repair_jpeg_header(fp, backup_dir=backup_dir)

    assert ok
    assert fp.read_bytes() == VALID_JPEG
    backups = list(backup_dir.glob("broken.jpg*.quarantined"))
    assert len(backups) == 1
    assert backups[0].read_bytes() + fp.read_bytes() == original


# ─────────────────────────────────────────────
# #5 — Renaming must not strip Hidden/System attributes
# ─────────────────────────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="NTFS file attributes are Windows-only")
def test_rename_preserves_hidden_attribute(tmp_path):
    import ctypes
    k32 = ctypes.windll.kernel32
    FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_HIDDEN = 0x1, 0x2

    src = tmp_path / "secret.jpg"
    src.write_bytes(b"h")
    assert k32.SetFileAttributesW(str(src), FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_READONLY)
    dst = tmp_path / "secret_renamed.jpg"

    ok, err = safe_rename_with_retry(src, dst)

    assert ok, err
    attrs = k32.GetFileAttributesW(str(dst))
    assert attrs != -1 and attrs != 0xFFFFFFFF
    assert attrs & FILE_ATTRIBUTE_HIDDEN, f"Hidden attribute lost (attrs=0x{attrs:x})"
    k32.SetFileAttributesW(str(dst), 0x80)  # let tmp cleanup delete it

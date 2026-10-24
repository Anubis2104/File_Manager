"""
core/workers.py
QThread-based worker classes for long-running operations (scan, rename, duplicate detection).
Ensures GUI remains responsive during heavy processing.

New workers added:
  MetadataRewriteWorker  — batch ExifTool tag rewrite via ArgfileMetadataEngine
  DupRenameWorker        — in-place duplicate rename (_dp) with WAL logging
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from core.scanner import DirectoryScanner, FileInfo
from core.renamer import RenameEngine, RenameOperation
from core.metadata import MetadataEngine
from core.cleaner import FolderCleaner
from utils.file_utils import RenameOperation as FileRenameOp
from utils.safe_log import log_swallowed


# ─────────────────────────────────────────────────────────────
# Scanner Worker
# ─────────────────────────────────────────────────────────────

class ScanWorker(QObject):
    """
    Run DirectoryScanner in a dedicated thread.
    Signals:
        file_found(FileInfo)             — emitted for each discovered file
        progress(int, int, str)          — (done_count, total_count, current_filename)
        finished(list[FileInfo])         — emitted when scan completes
        cancelled()                      — emitted when scan is stopped by user
        error(str)                       — emitted on unhandled exception
    """
    file_found = pyqtSignal(object)       # FileInfo
    progress   = pyqtSignal(int, int, str)# (done, total, filename)
    finished   = pyqtSignal(list)
    cancelled  = pyqtSignal()
    error      = pyqtSignal(str)

    def __init__(
        self,
        root: Path | list[Path],
        recursive: bool = True,
        max_workers: int = 8,
        exiftool_exe: str = "exiftool",
        parent=None,
    ):
        super().__init__(parent)
        self.roots = [root] if isinstance(root, Path) else list(root)
        self.recursive = recursive
        self.max_workers = max_workers
        self.exiftool_exe = exiftool_exe
        self._scanner: Optional[DirectoryScanner] = None
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        """Signal scanner to stop gracefully."""
        self._cancel_flag = True
        self._cancel_event.set()
        if self._scanner:
            self._scanner.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            results: list[FileInfo] = []

            for root_path in self.roots:
                if self.is_cancelled:
                    break
                self._scanner = DirectoryScanner(
                    root=root_path,
                    recursive=self.recursive,
                    max_workers=self.max_workers,
                    exiftool_exe=self.exiftool_exe,
                )

                def on_file(info: FileInfo, cur: int, tot: int):
                    results.append(info)
                    self.file_found.emit(info)
                    self.progress.emit(cur, tot, info.name)

                def on_error(path: Path, exc: Exception):
                    self.error.emit(f"{path}: {exc}")

                scanned = self._scanner.scan(on_file=on_file, on_error=on_error)
                if (self._scanner and self._scanner._cancel_flag) or self.is_cancelled:
                    self.cancelled.emit()
                    return

            if self.is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


def make_scan_thread(worker: ScanWorker) -> QThread:
    """Create QThread, move worker to it, wire start."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread


# ─────────────────────────────────────────────────────────────
# Rename Worker
# ─────────────────────────────────────────────────────────────

class RenameWorker(QObject):
    """
    Execute batch rename operations in a background thread.
    """
    progress  = pyqtSignal(int, int, str)   # (done, total, current_name)
    finished  = pyqtSignal(list)             # list of RenameOperation
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, ops: list[FileRenameOp] = None, logger=None, parent=None, operations: list[FileRenameOp] = None):
        super().__init__(parent)
        self.ops = ops if ops is not None else (operations or [])
        self.logger = logger
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            total = len(self.ops)
            for i, op in enumerate(self.ops):
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                op.execute()
                if self.logger:
                    try:
                        self.logger.log_rename_op(op)
                    except Exception as _bare_exc:
                        log_swallowed("WORKERS", _bare_exc, label="Bỏ qua lỗi")
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                self.progress.emit(i + 1, total, op.src.name)
            if self.is_cancelled:
                self.cancelled.emit()
                return
            self.finished.emit(self.ops)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# Metadata Strip Worker
# ─────────────────────────────────────────────────────────────

class MetadataStripWorker(QObject):
    """
    Safe-strip metadata from a list of files in background.
    """
    progress  = pyqtSignal(int, int, str)    # (done, total, filename)
    finished  = pyqtSignal(list)              # list of result dicts
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, paths: list[Path], exiftool_exe: str = "exiftool", parent=None):
        super().__init__(parent)
        self.paths = paths
        self.exiftool_exe = exiftool_exe
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            engine = MetadataEngine(self.exiftool_exe)
            total = len(self.paths)
            results = []
            for i, path in enumerate(self.paths):
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                ok, dt, err = engine.safe_strip(path)
                results.append({"path": path, "success": ok, "date": dt, "error": err})
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                self.progress.emit(i + 1, total, path.name)
            if self.is_cancelled:
                self.cancelled.emit()
                return
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# Duplicate Detection Worker
# ─────────────────────────────────────────────────────────────

class DupScanWorker(QObject):
    """
    Run duplicate detection (pHash / DINOv2 / both) in background.
    """
    progress  = pyqtSignal(int, int, str)   # (done, total, status_msg)
    finished  = pyqtSignal(list)             # list of DupGroup
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(
        self,
        image_paths: list[Path],
        engine_mode: str = "both",       # 'phash' | 'dinov2' | 'both'
        phash_threshold: int = 10,
        embedding_threshold: float = 0.95,
        model_name: str = "dinov2_vits14",
        batch_size: int = 32,
        device: str = "cuda",            # 'cuda' | 'cpu'
        parent=None,
    ):
        super().__init__(parent)
        self.image_paths = image_paths
        self.engine_mode = engine_mode
        self.device = device
        self.phash_threshold = phash_threshold
        self.embedding_threshold = embedding_threshold
        self.model_name = model_name
        self.batch_size = batch_size
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            from duplicate.dup_manager import DupManager
            mgr = DupManager(
                phash_threshold=self.phash_threshold,
                embedding_threshold=self.embedding_threshold,
                model_name=self.model_name,
                batch_size=self.batch_size,
                device=self.device,
            )

            def _prog(cur, tot, msg=""):
                if self.is_cancelled:
                    raise InterruptedError("Đã hủy bởi người dùng")
                self.progress.emit(cur, tot, msg)

            cancel_chk = lambda: self.is_cancelled

            if self.engine_mode == "phash":
                groups = mgr.find_duplicates_phash(self.image_paths, _prog, cancel_check=cancel_chk)
            elif self.engine_mode == "dinov2":
                groups = mgr.find_duplicates_embedding(self.image_paths, _prog, cancel_check=cancel_chk)
            else:
                groups = mgr.find_duplicates_both(self.image_paths, _prog, cancel_check=cancel_chk)

            if self.is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(groups)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# Folder Clean Worker
# ─────────────────────────────────────────────────────────────

class CleanWorker(QObject):
    """Find and delete empty folders in background."""
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(list)
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, root: Path, folders: Optional[list[Path]] = None, dry_run: bool = False, parent=None):
        super().__init__(parent)
        self.root = root
        self.folders = folders
        self.dry_run = dry_run
        self._cleaner: Optional[FolderCleaner] = None
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()
        if self._cleaner:
            self._cleaner.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        from core.app_logcat import logcat
        try:
            self._cleaner = FolderCleaner(self.root)
            logcat.i("CleanWorker", f"Bắt đầu CleanWorker (dry_run={self.dry_run}) tại: {self.root}")

            if self.folders is not None:
                folders = self.folders
            else:
                def _scan_prog(scanned_cnt, path):
                    if self.is_cancelled:
                        return
                    self.progress.emit(scanned_cnt, 0, str(path))

                folders = self._cleaner.scan(on_progress=_scan_prog)

            logcat.i("CleanWorker", f"Quét xong: tìm thấy {len(folders)} thư mục rỗng")
            if self.is_cancelled:
                logcat.w("CleanWorker", "Tiến trình quét thư mục rỗng đã bị hủy.")
                self.cancelled.emit()
                return

            def _clean_prog(cur, tot, p):
                if self.is_cancelled:
                    if self._cleaner:
                        self._cleaner.cancel()
                    return
                self.progress.emit(cur, tot, str(p))

            results = self._cleaner.clean(
                folders=folders,
                dry_run=self.dry_run,
                on_progress=_clean_prog,
            )
            if self.is_cancelled:
                logcat.w("CleanWorker", "Tiến trình xóa thư mục rỗng đã bị hủy.")
                self.cancelled.emit()
            else:
                logcat.i("CleanWorker", f"CleanWorker hoàn tất với {len(results)} kết quả.")
                self.finished.emit(results)
        except Exception as exc:
            logcat.e("CleanWorker", f"Lỗi trong CleanWorker: {exc}")
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# Duplicate Delete Worker
# ─────────────────────────────────────────────────────────────

class DupDeleteWorker(QObject):
    """
    Safely delete duplicate files using send2trash (Recycle Bin).
    """
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(list)
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, target_paths: list[Path], parent=None):
        super().__init__(parent)
        self.target_paths = target_paths
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        import send2trash
        results = []
        total = len(self.target_paths)
        for i, path in enumerate(self.target_paths):
            if self.is_cancelled:
                self.cancelled.emit()
                return
            res = {"path": path, "success": False, "error": ""}
            try:
                if path.exists():
                    send2trash.send2trash(str(path))
                    res["success"] = True
                else:
                    res["error"] = "File không tồn tại"
            except Exception as exc:
                res["error"] = str(exc)
            results.append(res)
            if self.is_cancelled:
                self.cancelled.emit()
                return
            self.progress.emit(i + 1, total, path.name)
        if self.is_cancelled:
            self.cancelled.emit()
        else:
            self.finished.emit(results)


# ─────────────────────────────────────────────────────────────
# MetadataRewriteWorker
# ─────────────────────────────────────────────────────────────

class MetadataRewriteWorker(QObject):
    """
    Batch-rewrite Artist, Copyright, UserComment tags across all namespaces
    using ArgfileMetadataEngine (ExifTool argfile, 150 files/chunk).

    Signals:
        progress(int, int, str)  — (processed, total, status_message)
        finished(int)            — number of files successfully updated
        cancelled()              — emitted when stopped by user
        error(str)
    """
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(int)             # count of updated files
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(
        self,
        files: List[Path],
        tags: Dict[str, str],
        strip_existing: bool = False,
        chunk_size: int = 150,
        exiftool_exe: str = "exiftool",
        parent=None,
    ):
        super().__init__(parent)
        self.files        = files
        self.tags         = tags
        self.strip_existing = strip_existing
        self.chunk_size   = chunk_size
        self.exiftool_exe = exiftool_exe
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        try:
            from core.metadata import ArgfileMetadataEngine
            engine  = ArgfileMetadataEngine(self.exiftool_exe)
            total   = len(self.files)
            updated = 0

            for i in range(0, total, self.chunk_size):
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                chunk = self.files[i : i + self.chunk_size]
                n = engine.rewrite_tags_batch(
                    chunk,
                    self.tags,
                    strip_existing=self.strip_existing,
                    chunk_size=self.chunk_size,
                )
                updated += n
                if self.is_cancelled:
                    self.cancelled.emit()
                    return
                self.progress.emit(
                    min(i + self.chunk_size, total),
                    total,
                    f"Updated {updated}/{total} files",
                )

            if self.is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(updated)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# DupRenameWorker
# ─────────────────────────────────────────────────────────────

class DupRenameWorker(QObject):
    """
    In-place rename of duplicate files using the _dp<group><token>[name] scheme.
    Each rename is logged to WAL TransactionManager for Rollback support.

    Target name format:
        <md5_8char>_dp<group_idx><token>[<original_stem>]<ext>
        Example: a3f9b12c_dp1A[IMG_0042].jpg

    Signals:
        progress(int, int, str)  — (done, total, current_filename)
        finished(list)           — list of result dicts {src, dst, success, error}
        cancelled()              — emitted on cancellation
        error(str)
    """
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(list)
    cancelled = pyqtSignal()
    error     = pyqtSignal(str)

    # Incrementing token alphabet for collision avoidance
    _TOKENS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

    def __init__(
        self,
        groups: List[List[Path]],
        log_dir: Optional[Path] = None,
        dry_run: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.groups  = groups
        self.log_dir = log_dir or Path.home() / ".file_manager_logs"
        self.dry_run = dry_run
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def _build_target_name(
        self,
        path: Path,
        group_idx: int,
        token: str,
    ) -> Path:
        """Build <hash8>_dp<G><tok>[<stem>]<ext> destination path.

        Automatically appends a numeric suffix (_01, _02 ...) if the target already
        exists so that concurrent workers cannot produce naming collisions.
        """
        from utils.file_utils import compute_md5, sanitize_filename
        try:
            h8 = compute_md5(path)[:8]
        except Exception:
            import hashlib
            h8 = hashlib.md5(path.name.encode()).hexdigest()[:8]
        stem_safe = sanitize_filename(path.stem)[:40]  # cap at 40 chars
        base_name = f"{h8}_dp{group_idx}{token}[{stem_safe}]{path.suffix.lower()}"
        candidate = path.parent / base_name
        # Collision guard: append suffix until a free name is found
        counter = 1
        while candidate.exists():
            suffix_name = f"{h8}_dp{group_idx}{token}[{stem_safe}]_{counter:02d}{path.suffix.lower()}"
            candidate = path.parent / suffix_name
            counter += 1
        return candidate

    def run(self):
        from core.logger import TransactionManager
        from utils.file_utils import safe_rename_with_retry, ensure_writable

        results = []
        total   = sum(len(g) for g in self.groups)
        done    = 0

        with TransactionManager(self.log_dir) as wal:
            for g_idx, group in enumerate(self.groups, start=1):
                for t_idx, path in enumerate(group):
                    if self.is_cancelled:
                        self.cancelled.emit()
                        return
                    token = self._TOKENS[t_idx % len(self._TOKENS)]
                    dst   = self._build_target_name(path, g_idx, token)
                    res   = {"src": str(path), "dst": str(dst), "success": False, "error": ""}

                    try:
                        if not path.exists():
                            res["error"] = "Source not found"
                        elif self.dry_run:
                            res["success"] = True
                        else:
                            ensure_writable(path)
                            ok, err = safe_rename_with_retry(path, dst)
                            res["success"] = ok
                            res["error"]   = err
                            if ok:
                                wal.log("RENAME_DUPLICATE", {
                                    "src": str(path),
                                    "dst": str(dst),
                                    "group": g_idx,
                                })
                    except Exception as exc:
                        res["error"] = str(exc)

                    results.append(res)
                    done += 1
                    if self.is_cancelled:
                        self.cancelled.emit()
                        return
                    self.progress.emit(done, total, path.name)

        if self.is_cancelled:
            self.cancelled.emit()
        else:
            self.finished.emit(results)


# ─────────────────────────────────────────────────────────────
# Byte Inspector & Security Worker
# ─────────────────────────────────────────────────────────────

class InspectorWorker(QObject):
    """
    Run 5-layer byte inspection and optional AMSI malware scanning in background thread.
    Signals:
        file_inspected(dict)           — emitted for each inspected file
        progress(int, int, str)        — (done_count, total_count, current_filename)
        finished(list)                 — emitted when scan completes
        cancelled()                    — emitted when cancelled by user
        error(str)                     — emitted on error
    """
    file_inspected = pyqtSignal(dict)
    progress       = pyqtSignal(int, int, str)
    finished       = pyqtSignal(list)
    cancelled      = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(
        self,
        root: Path,
        recursive: bool = True,
        run_amsi: bool = False,
        quarantine_dir: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.root = root
        self.recursive = recursive
        self.run_amsi = run_amsi
        self.quarantine_dir = quarantine_dir or (root / "_Quarantine")
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        from core.inspector import inspect_file
        from core.security import AmsiScanner, quarantine_file

        try:
            self._cancel_flag = False
            files_to_check: list[Path] = []
            excluded_names = {'_quarantine', '_Quarantine', '.git', '__pycache__', '.venv', '.vscode'}

            if self.recursive:
                for dirpath, dirs, files in os.walk(str(self.root)):
                    dirs[:] = [d for d in dirs if d not in excluded_names and not d.startswith(".")]
                    for f in files:
                        if f.lower().endswith('.quarantined') or f == 'quarantine_log.txt':
                            continue
                        files_to_check.append(Path(dirpath) / f)
            else:
                for f in self.root.iterdir():
                    if f.is_file() and not f.name.endswith('.quarantined'):
                        files_to_check.append(f)

            total = len(files_to_check)
            results = []
            amsi_scanner = AmsiScanner() if self.run_amsi else None

            for idx, fpath in enumerate(files_to_check, start=1):
                if self.is_cancelled:          # ← Dùng property nhất quán
                    self.cancelled.emit()
                    if amsi_scanner:
                        amsi_scanner.close()
                    return

                res = inspect_file(fpath)

                # Optional AMSI scan
                if self.run_amsi and amsi_scanner and amsi_scanner.available and res["status"] in ("CLEAN", "OVERLAY"):
                    is_detected, code, desc = amsi_scanner.scan_file(fpath)
                    if is_detected:
                        q_ok, q_target = quarantine_file(
                            fpath, self.quarantine_dir,
                            "VIRUS/MALWARE (AMSI)", f"Ma doc phat hien boi AMSI ({desc})"
                        )
                        res.update({
                            "status": "QUARANTINED",
                            "reason": "Virus/Malware (AMSI)",
                            "details": f"Ma doc AMSI code {code} -> Da cach ly vao {q_target}",
                            "action": "Da cach ly",
                        })

                # If threats like disguised PE or scripts need quarantine
                if res["status"] == "THREAT":
                    q_ok, q_target = quarantine_file(
                        fpath, self.quarantine_dir,
                        res.get("threat_type", "THREAT"), res.get("details", "")
                    )
                    if q_ok:
                        res["status"] = "QUARANTINED"
                        res["action"] = "Da cach ly"
                        res["details"] += f" (Luu tai {Path(q_target).name})"

                results.append(res)
                self.file_inspected.emit(res)
                self.progress.emit(idx, total, fpath.name)

            if amsi_scanner:
                amsi_scanner.close()

            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class TrimOverlayWorker(QObject):
    """
    Trim trailing overlay bytes from selected files in background.
    Signals:
        progress(int, int, str)   — (done, total, filename)
        finished(list)            — list of result dicts when all items processed
        cancelled()               — emitted when user cancels before completion
        error(str)                — emitted on unhandled exception
    """
    progress  = pyqtSignal(int, int, str)
    finished  = pyqtSignal(list)
    cancelled = pyqtSignal()          # ← Thêm cancelled signal
    error     = pyqtSignal(str)

    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self.items = items
        self._cancel_flag = False
        self._cancel_event = threading.Event()   # ← Thêm cancel event

    def cancel(self):
        self._cancel_flag = True
        self._cancel_event.set()                 # ← Set event khi cancel

    @property
    def is_cancelled(self) -> bool:              # ← Property nhất quán với workers khác
        return self._cancel_flag or self._cancel_event.is_set()

    def run(self):
        from core.inspector import trim_file_overlay

        try:
            results = []
            total = len(self.items)
            for idx, item in enumerate(self.items, start=1):
                if self.is_cancelled:            # ← Dùng property
                    self.cancelled.emit()        # ← Emit cancelled signal
                    return
                fpath = item.get("path")
                valid_end = item.get("valid_end_pos")
                ok, bytes_cut, msg = trim_file_overlay(fpath, valid_end)
                res = {
                    "path": fpath,
                    "success": ok,
                    "bytes_cut": bytes_cut,
                    "message": msg,
                }
                results.append(res)
                self.progress.emit(idx, total, Path(fpath).name if fpath else "")

            if self.is_cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))



# ─────────────────────────────────────────────────────────────
# Paste (Explorer-style copy / move)
# ─────────────────────────────────────────────────────────────

class PasteWorker(QObject):
    """Copy or move files/folders into a folder off the GUI thread (core.file_ops.paste)."""
    progress  = pyqtSignal(int, int, str)    # (done, total, current name)
    finished  = pyqtSignal(list)              # list[PasteResult]
    error     = pyqtSignal(str)

    def __init__(self, sources: list[Path], dest_dir: Path, move: bool, parent=None):
        super().__init__(parent)
        self.sources = list(sources)
        self.dest_dir = dest_dir
        self.move = move
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        from core.file_ops import paste
        try:
            results = paste(self.sources, self.dest_dir, self.move,
                            on_progress=lambda d, t, n: self.progress.emit(d, t, n),
                            cancel_check=self._cancel_event.is_set)
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))

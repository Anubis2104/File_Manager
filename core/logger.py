"""
core/logger.py
JSONL-based rename log with restore capability and checksum verification.
Also provides TransactionManager: a Write-Ahead Log (WAL) for all file
operations (rename, metadata rewrite, trash) with full Rollback support.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from utils.file_utils import compute_md5, RenameOperation


LOG_VERSION = "1.0"


class LogEntry:
    """A single operation record in the log file."""

    __slots__ = (
        "timestamp", "operation", "src_path", "dst_path",
        "src_name", "dst_name", "checksum_before", "checksum_after",
        "error",
    )

    def __init__(
        self,
        timestamp: datetime,
        operation: str,       # 'rename' | 'restore' | 'strip_metadata'
        src_path: str,
        dst_path: str,
        src_name: str,
        dst_name: str,
        checksum_before: str = "",
        checksum_after: str = "",
        error: str = "",
    ):
        self.timestamp = timestamp
        self.operation = operation
        self.src_path = src_path
        self.dst_path = dst_path
        self.src_name = src_name
        self.dst_name = dst_name
        self.checksum_before = checksum_before
        self.checksum_after = checksum_after
        self.error = error

    def to_dict(self) -> dict:
        return {
            "version":         LOG_VERSION,
            "timestamp":       self.timestamp.isoformat(),
            "operation":       self.operation,
            "src_path":        self.src_path,
            "dst_path":        self.dst_path,
            "src_name":        self.src_name,
            "dst_name":        self.dst_name,
            "checksum_before": self.checksum_before,
            "checksum_after":  self.checksum_after,
            "error":           self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LogEntry":
        return cls(
            timestamp=datetime.fromisoformat(d.get("timestamp", datetime.now().isoformat())),
            operation=d.get("operation", "rename"),
            src_path=d.get("src_path", ""),
            dst_path=d.get("dst_path", ""),
            src_name=d.get("src_name", ""),
            dst_name=d.get("dst_name", ""),
            checksum_before=d.get("checksum_before", ""),
            checksum_after=d.get("checksum_after", ""),
            error=d.get("error", ""),
        )

    def __repr__(self):
        return f"<LogEntry {self.operation}: {self.src_name!r} → {self.dst_name!r}>"


class RenameLogger:
    """
    Append-only JSONL logger for file rename/restore operations.

    File format (one JSON object per line):
        {"version":"1.0","timestamp":"...","operation":"rename","src_path":"...","dst_path":"...","src_name":"...","dst_name":"...","checksum_before":"...","checksum_after":"...","error":""}
    """

    def __init__(self, log_path: Path, compute_checksums: bool = True):
        self.log_path = log_path
        self.compute_checksums = compute_checksums

    def log_rename_op(self, op: RenameOperation) -> LogEntry:
        """Log a completed (or dry-run) RenameOperation."""
        if self.compute_checksums and not op.dry_run:
            target = op.dst if op.dst.exists() else op.src
            if target.exists():
                try:
                    fsize = target.stat().st_size
                    # For huge files (> 64 MB), limit hash to 32 MB to prevent disk bottlenecks
                    if fsize > 64 * 1024 * 1024:
                        checksum_after = compute_md5(target, max_bytes=32 * 1024 * 1024)
                    else:
                        checksum_after = compute_md5(target)
                except Exception:
                    checksum_after = ""
                checksum_before = checksum_after
            else:
                checksum_before = checksum_after = ""
        else:
            checksum_before = checksum_after = ""

        entry = LogEntry(
            timestamp=datetime.now(),
            operation="rename" if not op.dry_run else "dry_rename",
            src_path=str(op.src),
            dst_path=str(op.dst),
            src_name=op.src.name,
            dst_name=op.dst.name,
            checksum_before=checksum_before,
            checksum_after=checksum_after,
            error=op.error or "",
        )
        self._append(entry)
        return entry

    def log_batch(self, ops: list[RenameOperation]) -> list[LogEntry]:
        """Log all operations from a batch rename."""
        return [self.log_rename_op(op) for op in ops]

    def _append(self, entry: LogEntry) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    # ─────────────────────────────────────────────
    # Read / Restore
    # ─────────────────────────────────────────────

    def read_entries(self) -> list[LogEntry]:
        """Parse all log entries from the JSONL file."""
        if not self.log_path.exists():
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(LogEntry.from_dict(json.loads(line)))
                except json.JSONDecodeError:
                    pass
        return entries

    def restore_from_log(
        self,
        log_path: Optional[Path] = None,
        verify_checksum: bool = True,
        on_progress=None,
        cancel_check=None,
    ) -> list[dict]:
        """
        Reverse all rename operations in the log in LIFO order (newest first).
        Returns list of: {entry, success, error}
        """
        target_log = log_path or self.log_path
        tmp_logger = RenameLogger(target_log, compute_checksums=False)
        entries = tmp_logger.read_entries()

        # Only restore 'rename' operations (not dry_rename, not restore)
        rename_entries = [e for e in entries if e.operation == "rename"]
        rename_entries.reverse()  # newest first

        results = []
        for i, entry in enumerate(rename_entries):
            if cancel_check and cancel_check():
                break
            dst_path = Path(entry.dst_path)
            src_path = Path(entry.src_path)
            result = {"entry": entry, "success": False, "error": ""}

            if not dst_path.exists():
                result["error"] = f"File not found: {dst_path}"
                results.append(result)
                continue

            # Optional checksum verification
            if verify_checksum and entry.checksum_after:
                current_md5 = compute_md5(dst_path)
                if current_md5 != entry.checksum_after:
                    result["error"] = "Checksum mismatch — file may have been modified"
                    results.append(result)
                    continue

            try:
                dst_path.rename(src_path)
                result["success"] = True
                # Log the restore operation
                restore_entry = LogEntry(
                    timestamp=datetime.now(),
                    operation="restore",
                    src_path=str(dst_path),
                    dst_path=str(src_path),
                    src_name=dst_path.name,
                    dst_name=src_path.name,
                )
                self._append(restore_entry)
            except OSError as exc:
                result["error"] = str(exc)

            results.append(result)
            if on_progress:
                on_progress(i + 1, len(rename_entries))

        return results


# =============================================================================
# TransactionManager — Write-Ahead Log (WAL) for all file operations
# =============================================================================

class TransactionManager:
    """
    Append-only JSONL Write-Ahead Log for all file mutation operations.

    Supported action types:
        RENAME              — standard file rename/move
        RENAME_DUPLICATE    — in-place duplicate identifier rename (_dp)
        METADATA_REWRITE    — ExifTool tag overwrite with original state
        TRASH_DIR           — directory sent to Recycle Bin

    Each record is a single JSON line:
        {"timestamp": <float>, "iso_time": <str>, "action": <str>, "details": {...}}

    Rollback reverses records in reverse chronological order.
    Supports RENAME / RENAME_DUPLICATE and METADATA_REWRITE restoration.
    TRASH_DIR records print a manual reminder (files are in Recycle Bin).
    """

    RENAME_ACTIONS = {"RENAME", "RENAME_DUPLICATE"}

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.wal_path = self.log_dir / f"session_{ts}.jsonl"
        # line-buffered for crash safety
        self._file = open(self.wal_path, "a", encoding="utf-8", buffering=1)

    # ─────────────────────────────────────────────
    # Write
    # ─────────────────────────────────────────────

    def log(self, action: str, details: Dict[str, Any]) -> None:
        """Append a WAL record (thread-safe due to line buffering + GIL)."""
        record = {
            "timestamp": time.time(),
            "iso_time":  datetime.now().isoformat(),
            "action":    action,
            "details":   details,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self) -> None:
        """Flush and close the WAL file."""
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> "TransactionManager":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ─────────────────────────────────────────────
    # Read
    # ─────────────────────────────────────────────

    def read_records(
        self,
        wal_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Parse all WAL records from file. Returns list newest-first."""
        target = wal_path or self.wal_path
        if not target.exists():
            return []
        records = []
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

    # ─────────────────────────────────────────────
    # Rollback
    # ─────────────────────────────────────────────

    def rollback(
        self,
        wal_path: Optional[Path] = None,
        exiftool_exe: str = "exiftool",
        on_progress: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """
        Undo all operations recorded in the WAL in reverse chronological order.

        Supports:
            RENAME / RENAME_DUPLICATE  — renames dst back to src
            METADATA_REWRITE           — restores original tag values
            TRASH_DIR                  — prints manual reminder (no auto-restore)

        Returns list of result dicts: {action, src, dst, success, error}
        """
        from utils.file_utils import ensure_writable, safe_rename_with_retry
        from core.metadata import ArgfileMetadataEngine

        records = self.read_records(wal_path)
        records.reverse()  # newest first

        results = []
        engine: Optional[ArgfileMetadataEngine] = None

        for idx, record in enumerate(records):
            action  = record.get("action", "")
            details = record.get("details", {})
            result: Dict[str, Any] = {
                "action": action, "success": False, "error": ""
            }

            try:
                if action in self.RENAME_ACTIONS:
                    src = Path(details["src"])
                    dst = Path(details["dst"])
                    result["src"] = str(src)
                    result["dst"] = str(dst)

                    if not dst.exists():
                        result["error"] = f"File not found at dst: {dst}"
                    else:
                        ensure_writable(dst)
                        src.parent.mkdir(parents=True, exist_ok=True)
                        ok, err = safe_rename_with_retry(dst, src)
                        result["success"] = ok
                        result["error"]   = err

                elif action == "METADATA_REWRITE":
                    f_path = Path(details["file"])
                    orig   = details.get("original_tags", {})
                    result["src"] = str(f_path)

                    if f_path.exists() and orig:
                        if engine is None:
                            engine = ArgfileMetadataEngine(exiftool_exe)
                        ensure_writable(f_path)
                        restore_tags = {
                            "Artist":      orig.get("Artist") or orig.get("Creator") or "",
                            "Copyright":   orig.get("Copyright") or "",
                            "UserComment": orig.get("UserComment") or orig.get("Description") or "",
                        }
                        n_ok = engine.rewrite_tags_batch([f_path], restore_tags)
                        result["success"] = n_ok > 0
                    else:
                        result["error"] = "File missing or no original tags"

                elif action == "TRASH_DIR":
                    result["src"]    = details.get("path", "")
                    result["success"] = None   # manual
                    result["error"]  = "Directory was trashed. Restore manually from Recycle Bin."

            except Exception as exc:
                result["error"] = str(exc)

            results.append(result)
            if on_progress:
                on_progress(idx + 1, len(records))

        return results

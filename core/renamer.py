"""
core/renamer.py
Batch rename engine with collision handling and dry-run support.

Rename format: {FolderName}_{DDMMYY}_{H/V}_{WH}.{ext}
Example:       Camera_190826_H_19201080.jpg
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from core.scanner import FileInfo
from utils.date_utils import format_date_for_rename
from utils.file_utils import sanitize_filename, make_unique_path, RenameOperation


def build_new_name(
    info: FileInfo,
    date_fmt: str = "DDMMYY",
    pattern: Optional[str] = None,
    seq_idx: int = 1,
) -> str:
    """
    Build the target filename string (without parent path).
    Supports customizable token patterns or default standard naming.
    Tokens: {folder}, {date}, {orientation}, {resolution}, {seq}, {original}
    """
    folder = sanitize_filename(info.folder_name) or "Unknown"

    # Date component
    dt: Optional[datetime] = info.created
    if dt:
        date_part = format_date_for_rename(dt, date_fmt)
    else:
        date_part = "000000"  # fallback if no date found

    ext = info.extension  # already lowercase with dot

    if pattern and pattern.strip():
        p = pattern.strip()
        p = p.replace("{folder}", folder)
        p = p.replace("{date}", date_part)
        p = p.replace("{orientation}", info.orientation or "")
        p = p.replace("{resolution}", info.size_str or "")
        p = p.replace("{seq}", f"{seq_idx:03d}")
        p = p.replace("{original}", sanitize_filename(info.path.stem))
        # Remove consecutive or trailing underscores
        import re
        p = re.sub(r"_+", "_", p).strip("_")
        return f"{p}{ext}"

    if info.media_type in ("image", "raw", "video") and info.orientation and info.size_str:
        return f"{folder}_{date_part}_{info.orientation}_{info.size_str}{ext}"
    else:
        # Non-media: keep it simple, omit orientation/size
        return f"{folder}_{date_part}{ext}"


class RenameEngine:
    """
    Generates and executes rename operations for a list of FileInfo objects.
    Supports dry-run (preview) mode and custom naming patterns.
    """

    def __init__(
        self,
        date_fmt: str = "DDMMYY",
        pattern: Optional[str] = None,
        collision_digits: int = 3,
        dry_run: bool = True,
    ):
        self.date_fmt = date_fmt
        self.pattern = pattern
        self.collision_digits = collision_digits
        self.dry_run = dry_run

    def plan(self, files: list[FileInfo]) -> list[RenameOperation]:
        """
        Build a list of RenameOperation objects without executing them.
        Handles within-batch collision: if two files would get the same name,
        one is suffixed with _001, _002, etc.
        """
        ops: list[RenameOperation] = []
        # Track planned destinations to handle in-batch collisions
        planned_dsts: set[Path] = set()

        for idx, info in enumerate(files, start=1):
            new_name = build_new_name(info, self.date_fmt, pattern=self.pattern, seq_idx=idx)
            new_path = info.path.parent / new_name

            # Check collision: either destination exists on disk (and is NOT the current file)
            # or destination has already been claimed by another file in this batch
            if (new_path.exists() and new_path != info.path) or new_path in planned_dsts:
                # Find unique name considering both disk and reserved batch names
                candidate = self._find_unique(new_path, planned_dsts, exclude=info.path)
                new_path = candidate

            planned_dsts.add(new_path)
            ops.append(RenameOperation(
                src=info.path,
                dst=new_path,
                dry_run=self.dry_run,
            ))

        return ops

    def execute(self, ops: list[RenameOperation]) -> list[RenameOperation]:
        """
        Execute all RenameOperations.
        If dry_run=True on the engine, this is a no-op (ops are marked executed).
        Returns the list with executed/error flags set.
        """
        # Override dry_run flag on each op if engine-level changed
        for op in ops:
            op.dry_run = self.dry_run
            op.execute()
        return ops

    def plan_and_execute(self, files: list[FileInfo]) -> list[RenameOperation]:
        """Convenience: plan then execute immediately."""
        ops = self.plan(files)
        return self.execute(ops)

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    def _find_unique(self, path: Path, reserved: set[Path], exclude: Optional[Path] = None) -> Path:
        """Find a unique path not on disk (except possibly `exclude`) and not in reserved set."""
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter:0{self.collision_digits}d}{suffix}"
            if (not candidate.exists() or candidate == exclude) and candidate not in reserved:
                return candidate
            counter += 1

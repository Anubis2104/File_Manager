"""
core/scanner.py
Recursive directory scanner using ThreadPoolExecutor.
Emits FileInfo objects via callback for GUI progress updates.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from utils.date_utils import extract_best_date
from utils.file_utils import classify_extension, IMAGE_EXTS, VIDEO_EXTS
from utils.media_info import get_media_dimensions, MediaDimensions


@dataclass
class FileInfo:
    """All metadata for a single file, populated by the scanner."""
    path: Path
    name: str
    size: int                          # bytes
    created: Optional[datetime]
    created_source: str                # 'exif' | 'birthtime' | 'mtime' | 'unknown'
    modified: Optional[datetime]
    extension: str                     # lowercase, with dot
    media_type: str                    # 'image' | 'video' | 'other'
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: Optional[str] = None # 'H' | 'V'
    duration: Optional[float] = None  # seconds, for video
    checksum: Optional[str] = None    # lazy, computed on demand
    error: Optional[str] = None       # set if scan partially failed

    @property
    def folder_name(self) -> str:
        return self.path.parent.name

    @property
    def size_str(self) -> str:
        """Return WxH string like '19201080', or '' for non-media."""
        if self.width and self.height:
            return f"{self.width}{self.height}"
        return ""

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return isinstance(other, FileInfo) and self.path == other.path


ProgressCallback = Callable[[FileInfo], None]
ErrorCallback    = Callable[[Path, Exception], None]


class DirectoryScanner:
    """
    Scans a directory tree and builds FileInfo objects for all files.
    Thread-safe: each file is processed in an isolated thread.
    """

    def __init__(
        self,
        root: Path,
        recursive: bool = True,
        max_workers: int = 8,
        exiftool_exe: str = "exiftool",
        include_media_dimensions: bool = True,
    ):
        self.root = root
        self.recursive = recursive
        self.max_workers = max_workers
        self.exiftool_exe = exiftool_exe
        self.include_media_dimensions = include_media_dimensions
        self._cancel_flag = False

    def cancel(self) -> None:
        """Signal the scanner to stop after current batch."""
        self._cancel_flag = True

    def scan(
        self,
        on_file: Optional[Callable[[FileInfo, int, int], None]] = None,
        on_error: Optional[ErrorCallback] = None,
    ) -> list[FileInfo]:
        """
        Scan directory and return list of FileInfo.
        `on_file(info, current_done, total_count)` is called as each file completes.
        """
        self._cancel_flag = False
        paths = list(self._collect_paths())
        total = len(paths)

        results: list[FileInfo] = []
        done_count = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(self._process_file, p): p for p in paths
            }
            for future in as_completed(future_map):
                if self._cancel_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                src_path = future_map[future]
                done_count += 1
                try:
                    info = future.result()
                    results.append(info)
                    if on_file:
                        on_file(info, done_count, total)
                except Exception as exc:
                    if on_error:
                        on_error(src_path, exc)

        return results

    def scan_file(self, path: Path) -> FileInfo:
        """Process a single file and return FileInfo object."""
        return self._process_file(path)

    scan_single_file = scan_file

    def scan_paths(
        self,
        paths: list[Path],
        on_error: Optional[ErrorCallback] = None,
    ) -> list[FileInfo]:
        """Process a specific list of file paths in parallel using threads.

        Args:
            paths:    List of file paths to process.
            on_error: Optional callback(path, exc) called for each failed file.
        """
        if not paths:
            return []
        # Reset cancel flag so prior cancel state does not immediately abort this scan
        self._cancel_flag = False
        if len(paths) == 1:
            try:
                return [self._process_file(paths[0])]
            except Exception as exc:
                if on_error:
                    on_error(paths[0], exc)
                return []
        results: list[FileInfo] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(self._process_file, p): p for p in paths}
            for future in as_completed(future_map):
                if self._cancel_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                src_path = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    # Log the error instead of silently dropping the file
                    try:
                        from core.app_logcat import logcat
                        logcat.w("Scanner", f"scan_paths: lỗi xử lý {src_path.name}: {exc}")
                    except Exception:
                        pass
                    if on_error:
                        on_error(src_path, exc)
        # Preserve original path ordering
        path_to_info = {f.path: f for f in results}
        return [path_to_info[p] for p in paths if p in path_to_info]

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    def _collect_paths(self):
        """Walk the directory tree and yield file paths (excluding system junk & customization INIs)."""
        from utils.file_utils import is_safe_folder_customization_ini
        walk = os.walk(str(self.root)) if self.recursive else self._shallow_walk()
        for dirpath, _dirs, filenames in walk:
            if self._cancel_flag:
                break
            for fname in filenames:
                if self._cancel_flag:
                    break
                f_lower = fname.lower()
                if f_lower in ("thumbs.db", ".ds_store"):
                    continue
                p = Path(dirpath) / fname
                if is_safe_folder_customization_ini(p):
                    continue
                yield p

    def _shallow_walk(self):
        """Single-level walk (non-recursive)."""
        items = list(os.scandir(str(self.root)))
        files = [e.name for e in items if e.is_file()]
        yield str(self.root), [], files

    def _process_file(self, path: Path) -> FileInfo:
        """Build a FileInfo for a single file. Runs in worker thread."""
        try:
            stat = path.stat()
            ext  = path.suffix.lower()
            mtype = classify_extension(ext)
            modified = datetime.fromtimestamp(stat.st_mtime)

            # Date extraction (EXIF-aware)
            created, created_source = extract_best_date(path, self.exiftool_exe)

            # Media dimensions
            width = height = None
            orientation = None
            duration = None
            if self.include_media_dimensions and mtype in ("image", "raw", "video"):
                dims: Optional[MediaDimensions] = get_media_dimensions(path)
                if dims:
                    width = dims.width
                    height = dims.height
                    orientation = dims.orientation
                    duration = dims.duration_secs if mtype == "video" else None

            return FileInfo(
                path=path,
                name=path.name,
                size=stat.st_size,
                created=created,
                created_source=created_source,
                modified=modified,
                extension=ext,
                media_type=mtype,
                width=width,
                height=height,
                orientation=orientation,
                duration=duration,
            )

        except Exception as exc:
            return FileInfo(
                path=path,
                name=path.name,
                size=0,
                created=None,
                created_source="unknown",
                modified=None,
                extension=path.suffix.lower(),
                media_type="other",
                error=str(exc),
            )

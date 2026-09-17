"""
core/cleaner.py
Find and delete empty folders by sending them to Windows Recycle Bin.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import os
from typing import Callable, Optional

import send2trash


def find_empty_folders(
    root: Path,
    recursive: bool = True,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, Path], None]] = None,
) -> list[Path]:
    """
    Return list of empty directories under `root`.
    A folder is considered empty if it contains no files (recursively),
    including parent folders whose subfolders are all empty.
    Sorted deepest-first so children are cleaned before parents.
    """
    empty: list[Path] = []
    empty_set: set[Path] = set()

    root = Path(root)
    if not root.exists() or not root.is_dir():
        return empty

    scanned = 0

    if recursive:
        # Walk bottom-up so we detect newly-emptied parents.
        # followlinks=False prevents infinite loops on Windows NTFS junctions.
        from utils.file_utils import is_safe_folder_customization_ini

        for dirpath, dirs, files in os.walk(str(root), topdown=False, followlinks=False):
            if cancel_check and cancel_check():
                break

            p = Path(dirpath)
            if p == root:
                continue  # Never delete root itself

            scanned += 1
            if on_progress and (scanned % 15 == 0 or not files):
                on_progress(scanned, p)

            # Check if directory contains real user files (ignoring safe customization INIs and system junk)
            has_user_files = False
            for f in files:
                f_lower = f.lower()
                if f_lower in ("thumbs.db", ".ds_store"):
                    continue
                file_p = p / f
                if is_safe_folder_customization_ini(file_p):
                    continue
                has_user_files = True
                break

            if has_user_files:
                continue

            try:
                # All subdirectories were already processed bottom-up
                if all((p / d) in empty_set for d in dirs):
                    empty.append(p)
                    empty_set.add(p)
            except (PermissionError, OSError):
                pass
    else:
        from utils.file_utils import is_safe_folder_customization_ini
        try:
            for child in root.iterdir():
                if cancel_check and cancel_check():
                    break
                if child.is_dir():
                    scanned += 1
                    if on_progress:
                        on_progress(scanned, child)
                    try:
                        has_content = False
                        for sub in child.iterdir():
                            if sub.is_dir():
                                has_content = True
                                break
                            sub_name = sub.name.lower()
                            if sub_name in ("thumbs.db", ".ds_store"):
                                continue
                            if is_safe_folder_customization_ini(sub):
                                continue
                            has_content = True
                            break
                        if not has_content:
                            empty.append(child)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    return empty


class FolderCleaner:
    """
    Scan for empty folders and delete them via send2trash (Windows Recycle Bin).
    """

    def __init__(self, root: Path, recursive: bool = True):
        self.root = root
        self.recursive = recursive
        self._cancel_flag = False

    def cancel(self):
        self._cancel_flag = True

    def scan(self, on_progress: Optional[Callable[[int, Path], None]] = None) -> list[Path]:
        """Return list of empty folders without deleting."""
        return find_empty_folders(
            self.root,
            self.recursive,
            cancel_check=lambda: self._cancel_flag,
            on_progress=on_progress,
        )

    def clean(
        self,
        folders: Optional[list[Path]] = None,
        dry_run: bool = False,
        on_progress: Optional[callable] = None,
    ) -> list[dict]:
        """
        Send empty folders to Recycle Bin.

        Args:
            folders:     Explicit list to clean. If None, auto-scans.
            dry_run:     If True, reports what would be deleted without acting.
            on_progress: Callback(current, total, path).

        Returns:
            List of {path, success, error, dry_run}
        """
        self._cancel_flag = False
        targets = folders if folders is not None else self.scan()
        results = []

        for i, folder in enumerate(targets):
            if self._cancel_flag:
                break
            result = {
                "path": folder,
                "success": False,
                "error": "",
                "dry_run": dry_run,
            }
            if dry_run:
                result["success"] = True
            else:
                try:
                    send2trash.send2trash(str(folder))
                    result["success"] = True
                except Exception as exc:
                    result["error"] = str(exc)

            results.append(result)
            if on_progress:
                on_progress(i + 1, len(targets), folder)

        return results

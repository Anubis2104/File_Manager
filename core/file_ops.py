"""
core/file_ops.py
Explorer-style paste (copy / move) of files and folders.

Rules (matching File Explorer where it does not need to ask the user):
- copying into the folder an item already lives in creates "name - Copy.ext",
  then "name - Copy (2).ext", ...;
- any other name clash gets " (2)", " (3)", ... — existing files are never overwritten;
- moving an item into the folder it is already in does nothing;
- a folder can never be copied or moved into itself or one of its subfolders.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass
class PasteResult:
    src: Path
    dst: Optional[Path]
    ok: bool
    skipped: bool = False
    error: str = ""


def _split_name(name: str, is_dir: bool) -> tuple[str, str]:
    if is_dir:
        return name, ""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:                 # ".gitignore", "README"
        return name, ""
    return stem, "." + ext


def explorer_copy_name(dest_dir: Path, name: str, is_dir: bool) -> Path:
    """'photo - Copy.jpg', then 'photo - Copy (2).jpg', ... (first one that does not exist)."""
    stem, ext = _split_name(name, is_dir)
    candidate = dest_dir / f"{stem} - Copy{ext}"
    n = 2
    while candidate.exists():
        candidate = dest_dir / f"{stem} - Copy ({n}){ext}"
        n += 1
    return candidate


def unique_name(dest_dir: Path, name: str, is_dir: bool) -> Path:
    """`name` if free, else 'name (2).ext', 'name (3).ext', ..."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, ext = _split_name(name, is_dir)
    n = 2
    while True:
        candidate = dest_dir / f"{stem} ({n}){ext}"
        if not candidate.exists():
            return candidate
        n += 1


def _is_inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def paste(
    sources: Iterable[Path],
    dest_dir: Path,
    move: bool,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[PasteResult]:
    """Copy (or move) `sources` into `dest_dir`. Returns one result per source, in order."""
    items = [Path(s) for s in sources]
    dest_dir = Path(dest_dir)
    results: list[PasteResult] = []

    for i, src in enumerate(items):
        if cancel_check and cancel_check():
            break
        if on_progress:
            on_progress(i, len(items), src.name)
        try:
            if not src.exists():
                results.append(PasteResult(src, None, False, error="Không tìm thấy tệp nguồn"))
                continue
            is_dir = src.is_dir()
            if is_dir and _is_inside(dest_dir, src):
                results.append(PasteResult(src, None, False,
                                           error="Không thể đặt thư mục vào chính nó hoặc thư mục con của nó"))
                continue

            same_folder = src.parent.resolve() == dest_dir.resolve()
            if move and same_folder:
                results.append(PasteResult(src, src, True, skipped=True))
                continue

            if same_folder:
                dst = explorer_copy_name(dest_dir, src.name, is_dir)
            else:
                dst = unique_name(dest_dir, src.name, is_dir)

            if move:
                shutil.move(str(src), str(dst))        # rename on the same volume, copy+delete across
            elif is_dir:
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst)
            results.append(PasteResult(src, dst, True))
        except OSError as exc:
            results.append(PasteResult(src, None, False, error=str(exc)))

    if on_progress:
        on_progress(len(results), len(items), "")
    return results


def summarize(results: list[PasteResult]) -> tuple[int, list[str]]:
    """(number pasted, error lines) for status messages."""
    done = sum(1 for r in results if r.ok and not r.skipped)
    errors = [f"{r.src.name}: {r.error}" for r in results if not r.ok]
    return done, errors


_ILLEGAL_CHARS = set('\\/:*?"<>|')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def invalid_filename_reason(name: str) -> str:
    """Why Windows would reject `name` as a file/folder name ('' if it is fine)."""
    if not name.strip():
        return "Tên không được để trống."
    bad = sorted({c for c in name if c in _ILLEGAL_CHARS or ord(c) < 32})
    if bad:
        return 'Tên tệp không được chứa các ký tự sau: \\ / : * ? " < > |'
    if name.endswith((".", " ")):
        return "Tên tệp không được kết thúc bằng dấu chấm hoặc khoảng trắng."
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        return f"'{name}' là tên dành riêng của Windows."
    return ""


def is_same_volume(a: Path, b: Path) -> bool:
    return os.path.splitdrive(str(a.resolve()))[0].lower() == os.path.splitdrive(str(b.resolve()))[0].lower()

"""
utils/file_utils.py
File utility functions: hashing, name sanitization, dry-run helpers,
Windows lock/permission handler (ensure_writable, safe_rename with backoff).
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Generator, Optional


# ─────────────────────────────────────────────
# Checksum / Hashing
# ─────────────────────────────────────────────

def compute_md5(path: Path, chunk_size: int = 1 << 20, max_bytes: Optional[int] = None) -> str:
    """Compute MD5 hex digest of a file (1 MB chunks). If max_bytes is set, hash up to max_bytes."""
    h = hashlib.md5()
    total_read = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
            total_read += len(chunk)
            if max_bytes and total_read >= max_bytes:
                break
    return h.hexdigest()


def compute_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────
# Windows Lock & Permission Handler
# ─────────────────────────────────────────────

_FILE_ATTRIBUTE_NORMAL = 0x80


def ensure_writable(path: Path) -> bool:
    """
    Gỡ bỏ triệt để cờ Read-Only, System, Hidden bằng Win32 API Kernel32 và chmod.
    Tự động cấp quyền Full Control qua icacls nếu gặp lỗi phân quyền NTFS.
    An toàn trên cả Windows và non-Windows.
    """
    try:
        if not path.exists():
            return False
        p_str = str(path.resolve())

        # 1. Reset attributes via Win32 Kernel32 (Windows only)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(p_str, _FILE_ATTRIBUTE_NORMAL)
            except Exception:
                pass

        # 2. Remove read-only flag via chmod (cross-platform)
        try:
            current_mode = os.stat(p_str).st_mode
            os.chmod(p_str, current_mode | stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass

        return True

    except Exception:
        # 3. Last-resort: grant NTFS full control via icacls (Windows only)
        if sys.platform == "win32":
            try:
                user = os.environ.get("USERNAME") or (os.getlogin() if hasattr(os, "getlogin") else "")
                if user:
                    subprocess.run(
                        ["icacls", str(path.resolve()), "/grant", f"{user}:F", "/c", "/q"],
                        capture_output=True,
                        timeout=5,
                    )
                    return True
            except Exception:
                pass
        return False


def safe_rename_with_retry(
    src: Path,
    dst: Path,
    max_retries: int = 8,
    base_delay: float = 0.05,
) -> tuple[bool, str]:
    """
    Đổi tên file an toàn với Exponential Backoff chống xung đột lock trên Windows.
    - Hỗ trợ đổi tên Case-only (photo.jpg -> Photo.jpg) an toàn 2 bước trên NTFS.
    - Tự động gỡ Read-Only qua ensure_writable() trước mỗi lần thử.
    - Hỗ trợ Windows long path (> 240 chars).
    - max_retries=8, delay tăng gấp đôi: 50ms → 6.4s tổng cộng.
    """
    src_safe = safe_long_path(src)
    dst_safe = safe_long_path(dst)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Case-only rename on Windows NTFS (e.g. photo.jpg -> Photo.jpg)
    is_case_only = (
        sys.platform == "win32"
        and src.parent.resolve() == dst.parent.resolve()
        and src.name.lower() == dst.name.lower()
        and src.name != dst.name
    )

    last_err = ""
    for attempt in range(max_retries):
        ensure_writable(src)
        if dst.exists() and not is_case_only:
            ensure_writable(dst)

        try:
            if is_case_only:
                import uuid
                tmp_name = f"._fmpro_case_{uuid.uuid4().hex[:8]}_{src.name}"
                tmp_path = safe_long_path(src.parent / tmp_name)
                os.rename(src_safe, tmp_path)
                try:
                    os.rename(tmp_path, dst_safe)
                    return True, ""
                except Exception as inner_exc:
                    # Rollback if second step fails
                    if Path(tmp_path).exists():
                        try:
                            os.rename(tmp_path, src_safe)
                        except Exception:
                            pass
                    raise inner_exc
            else:
                os.rename(src_safe, dst_safe)
                return True, ""
        except (PermissionError, OSError) as exc:
            last_err = str(exc)
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))

    return False, last_err


def clean_exiftool_temp_files(target_dir: Path) -> int:
    """
    Quét và xóa sạch các file tạm '_exiftool_tmp' sót lại do tiến trình trước bị
    gián đoạn. Trả về số file đã xóa.
    """
    removed = 0
    if not target_dir.exists():
        return 0
    for root, _, files in os.walk(target_dir):
        for fname in files:
            if "_exiftool_tmp" in fname:
                p = Path(root) / fname
                ensure_writable(p)
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except Exception:
                    pass
    return removed


# ─────────────────────────────────────────────
# Name Sanitization
# ─────────────────────────────────────────────

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING      = re.compile(r'[\s.]+$')
_SPACES        = re.compile(r'\s+')


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    Make a string safe for use as a Windows filename component.
    - Normalize unicode (NFC)
    - Remove / replace illegal characters
    - Collapse multiple spaces/underscores
    - Strip trailing dots and spaces
    """
    name = unicodedata.normalize("NFC", name)
    name = _ILLEGAL_CHARS.sub(replacement, name)
    name = _SPACES.sub(replacement, name)
    name = _TRAILING.sub("", name)
    # Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    reserved = re.compile(
        r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$', re.IGNORECASE
    )
    if reserved.match(name):
        name = f"_{name}"
    return name or replacement


def make_unique_path(path: Path, digits: int = 3) -> Path:
    """
    If `path` already exists, append _001, _002, ... until unique.
    Example: Camera_190826_H_19201080.jpg -> Camera_190826_H_19201080_001.jpg
    """
    if not path.exists():
        return path
    stem   = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter:0{digits}d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def safe_long_path(path: Path) -> Path:
    """Ensure Windows long path compatibility (> 240 chars)."""
    if os.name != "nt":
        return path
    s = str(path.resolve())
    if len(s) >= 240 and not s.startswith("\\\\?\\"):
        return Path(f"\\\\?\\{s}")
    return path


# ─────────────────────────────────────────────
# Dry-run Support
# ─────────────────────────────────────────────

class RenameOperation:
    """Represents a single rename/move operation (pending or completed)."""
    __slots__ = ("src", "dst", "dry_run", "executed", "error", "original_name")

    def __init__(self, src: Path, dst: Path, dry_run: bool = True, original_name: Optional[str] = None, **kwargs):
        self.src: Path      = src
        self.dst: Path      = dst
        self.dry_run: bool  = dry_run
        self.executed: bool = False
        self.error: str | None = None
        self.original_name: str | None = original_name or (src.name if hasattr(src, "name") else str(src))

    def execute(self) -> bool:
        """Perform the rename with retry and long path safety. Returns True on success."""
        if self.dry_run:
            self.executed = True
            return True
        if self.src == self.dst:
            self.executed = True
            return True
        ok, err = safe_rename_with_retry(self.src, self.dst)
        if ok:
            self.executed = True
            self.src = self.dst   # ← Cập nhật src để tránh stale path sau khi rename
            return True
        else:
            self.error = err
            return False

    def __repr__(self) -> str:
        mode = "[DRY]" if self.dry_run else "[LIVE]"
        return f"RenameOp{mode} {self.src.name!r} -> {self.dst.name!r}"


# ─────────────────────────────────────────────
# Directory Walk Helpers & Extension Sets
# ─────────────────────────────────────────────

IMAGE_EXTS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".tiff", ".tif", ".avif", ".heic", ".heif", ".gif"
})

RAW_EXTS: frozenset[str] = frozenset({
    ".cr2", ".cr3", ".nef", ".arw", ".dng",
    ".raf", ".orf", ".rw2", ".pef", ".srw",
})

VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mkv", ".mov", ".webm",
    ".wmv", ".flv", ".m4v", ".3gp"
})


def classify_extension(ext: str) -> str:
    """Return 'image', 'raw', 'video', or 'other' for a file extension."""
    e = ext.lower()
    if e in IMAGE_EXTS:
        return "image"
    if e in RAW_EXTS:
        return "raw"
    if e in VIDEO_EXTS:
        return "video"
    return "other"


def iter_files(root: Path, recursive: bool = True) -> Generator[Path, None, None]:
    """Yield all files under root, optionally recursively."""
    if recursive:
        for p in root.rglob("*"):
            if p.is_file():
                yield p
    else:
        for p in root.iterdir():
            if p.is_file():
                yield p


DANGEROUS_MASQUERADE_EXTS: frozenset[str] = frozenset({
    ".exe", ".scr", ".pif", ".com", ".bat", ".cmd", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".ps1xml", ".hta", ".msi",
    ".msp", ".cpl", ".dll", ".sys", ".bin"
})

SUSPICIOUS_SCRIPT_PATTERNS: tuple[bytes, ...] = (
    b"wscript.shell", b"powershell", b"cmd.exe", b"<?php",
    b"eval(", b"base64_decode(", b"shell_exec(", b"passthru(",
)


def is_safe_folder_customization_ini(path: Path | str) -> bool:
    """
    Check whether `path` is a legitimate folder customization .ini file
    (e.g., desktop.ini, folder.ini) and NOT a masqueraded executable/script.

    Validations:
    1. Suffix must be '.ini' (case-insensitive).
    2. Stem suffix must NOT be in DANGEROUS_MASQUERADE_EXTS (e.g. 'foo.exe.ini').
    3. File size must not exceed 512 KB.
    4. Binary header must NOT be PE executable (b'MZ') or ELF (b'\\x7fELF').
    5. Content must NOT contain known malicious shell execution patterns.
    6. Content must be decodable as text and contain valid INI structure/headers.
    """
    fp = Path(path)
    if not fp.is_file():
        return False

    name_lower = fp.name.lower()
    if not name_lower.endswith(".ini"):
        return False

    # Check for double extension / disguised executable (e.g. virus.exe.ini)
    stem_lower = fp.stem.lower()
    inner_ext = Path(stem_lower).suffix
    if inner_ext in DANGEROUS_MASQUERADE_EXTS:
        return False

    # Folder customization INI files are never massive
    try:
        size = fp.stat().st_size
        if size == 0:
            return True  # Zero-byte desktop.ini is safe junk
        if size > 512 * 1024:  # > 512 KB is suspicious for a folder ini
            return False

        with open(fp, "rb") as f:
            header = f.read(min(size, 4096))

        # Check binary headers (MZ for PE executables, ELF for unix binaries)
        if header.startswith(b"MZ") or header.startswith(b"\x7fELF"):
            return False

        header_lower = header.lower()
        for pat in SUSPICIOUS_SCRIPT_PATTERNS:
            if pat in header_lower:
                return False

        # Attempt decoding text (UTF-8, UTF-16 LE/BE, or latin-1)
        text = ""
        for enc in ("utf-8-sig", "utf-16", "utf-8", "cp1252", "latin-1"):
            try:
                text = header.decode(enc)
                break
            except (UnicodeDecodeError, ValueError):
                continue

        if not text:
            return False

        # Check for standard INI structures (section brackets or key=value pairs)
        has_section = any(line.strip().startswith("[") and "]" in line for line in text.splitlines())
        has_keyval = any("=" in line and not line.strip().startswith(";") for line in text.splitlines())

        # desktop.ini commonly has [.ShellClassInfo], [ViewState], etc.
        return has_section or has_keyval
    except Exception:
        return False


def get_app_dir() -> Path:
    """
    Returns the root directory of the application.
    Supports standard execution (from source) and PyInstaller frozen execution (standalone .exe).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent




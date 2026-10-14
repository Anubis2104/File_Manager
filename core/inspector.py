"""
core/inspector.py
Multi-layered binary inspection, format integrity verification,
trailing overlay auto-trimming, and header repair.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import mmap
import os
import shutil
import struct
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from utils.safe_log import log_swallowed, safe_log

VALID_MEDIA_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov', '.mkv', '.avi', '.gif', '.bmp', '.tiff'}
SYSTEM_JUNK_FILES = {'thumbs.db', 'desktop.ini', '.ds_store'}

DANGEROUS_EXTENSIONS = {
    '.exe', '.scr', '.pif', '.com', '.bat', '.cmd', '.vbs', '.vbe',
    '.js', '.jse', '.wsf', '.wsh', '.ps1', '.ps1xml', '.hta', '.msi', '.msp', '.cpl'
}

MALICIOUS_SCRIPT_PATTERNS = [
    b'<?php', b'eval(', b'base64_decode(', b'system(', b'shell_exec(',
    b'passthru(', b'wscript.shell', b'powershell -', b'<script'
]


def format_bytes(size: int) -> str:
    """Format byte count into human-readable string."""
    if size < 1024:
        return f"{size} B"
    for unit in ['KB', 'MB', 'GB', 'TB']:
        size /= 1024.0
        if size < 1024.0:
            return f"{size:.2f} {unit}"
    return f"{size:.2f} PB"


@contextlib.contextmanager
def _map_file(fp: Path) -> Iterator[mmap.mmap]:
    """Read-only memory map: byte search without loading the whole file into RAM."""
    with open(fp, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        yield mm


def _restore_times(fp: Path, st: os.stat_result) -> None:
    """
    Best-effort: keep original atime/mtime (mtime is the date fallback for renaming).
    Must never turn an already-applied modification into a reported failure.
    """
    try:
        os.utime(fp, (st.st_atime, st.st_mtime))
    except OSError as exc:
        safe_log("w", "INSPECTOR", f"Khong giu duoc thoi gian goc cua {fp.name}: {exc}")


def _default_backup_dir(fp: Path) -> Path:
    return fp.parent / "_Quarantine"


def _save_removed_bytes(
    fp: Path, start: int, end: int, backup_dir: Path, kind: str,
) -> Path:
    """
    Copy bytes [start, end) of `fp` into `backup_dir` before they are destroyed,
    so the original file can be rebuilt (prefix + file, or file + overlay).
    Raises on failure — callers must NOT modify the file if this fails.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{fp.name}_{ts}_{kind}.quarantined"
    counter = 1
    while target.exists():
        target = backup_dir / f"{fp.name}_{ts}_{kind}_{counter}.quarantined"
        counter += 1

    hasher = hashlib.sha256()
    remaining = end - start
    with open(fp, "rb") as src, open(target, "wb") as dst:
        src.seek(start)
        while remaining > 0:
            chunk = src.read(min(remaining, 1 << 20))
            if not chunk:
                break
            dst.write(chunk)
            hasher.update(chunk)
            remaining -= len(chunk)
    if remaining:
        target.unlink(missing_ok=True)
        raise IOError(f"Short read while backing up {fp.name}")

    log_line = (
        f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] TEP: {fp} | THAO TAC: {kind} | "
        f"BYTES: {start}-{end} ({end - start}) | SHA256: {hasher.hexdigest()} | LUU TAI: {target}\n"
    )
    with open(backup_dir / "quarantine_log.txt", "a", encoding="utf-8") as lf:
        lf.write(log_line)
    return target


def repair_jpeg_header(
    filepath: Path | str, backup_dir: Optional[Path | str] = None,
) -> Tuple[bool, str]:
    """
    Repair JPEG file by scanning for standard SOI marker (0xFF 0xD8 0xFF).
    Trims corrupted leading prefix (byheader error).
    The removed prefix is saved to `backup_dir` (default: <folder>/_Quarantine)
    and the file is replaced atomically with its timestamps preserved.
    """
    fp = Path(filepath)
    if not fp.is_file():
        return False, "Tep tin khong ton tai"

    jpeg_header = b'\xff\xd8\xff'
    try:
        st = fp.stat()
        if st.st_size == 0:
            return False, "Tep rong (0 bytes)"
        with _map_file(fp) as content:
            header_idx = content.find(jpeg_header)
        if header_idx == -1:
            return False, "Khong tim thay marker JPEG SOI hop le"
        if header_idx == 0:
            return True, "Header JPEG da hop le"

        q_dir = Path(backup_dir) if backup_dir else _default_backup_dir(fp)
        saved = _save_removed_bytes(fp, 0, header_idx, q_dir, "header_prefix")

        tmp = fp.with_name(f".{fp.name}.fmpro_repair.tmp")
        try:
            with open(fp, "rb") as src, open(tmp, "wb") as dst:
                src.seek(header_idx)
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(tmp, fp)
        finally:
            tmp.unlink(missing_ok=True)
        _restore_times(fp, st)
        return True, f"Da cat bo {header_idx} bytes loi o header (sao luu: {saved.name})"
    except Exception as exc:
        return False, f"Loi khi xu ly: {exc}"


def strip_trailing_data(filepath: Path | str, valid_end_pos: int) -> bool:
    """
    Truncate file in-place at valid_end_pos to remove trailing overlay.
    Low-level primitive with no backup — use trim_file_overlay() instead.
    """
    try:
        st = os.stat(filepath)
        with open(filepath, "r+b") as f:
            f.seek(valid_end_pos)
            f.truncate()
    except Exception:
        return False
    _restore_times(Path(filepath), st)
    return True


def inspect_file(filepath: Path | str) -> Dict[str, Any]:
    """
    Execute 4-layer structural byte inspection on a single file:
      - Layer 1: Empty file (0 bytes) and corrupted block (null/0xFF dump).
      - Layer 2: Disguised executables (PE MZ / Linux ELF / scripts disguised as media).
      - Layer 3: WebShell / script injection inside media files.
      - Layer 4: Structural integrity and Trailing Overlay detection for JPEG, PNG, WEBP, GIF.
    """
    fp = Path(filepath)
    fname = fp.name
    res: Dict[str, Any] = {
        "file": fname,
        "path": str(fp),
        "status": "CLEAN",
        "reason": "Hop le",
        "details": "",
        "bytes_stripped": 0,
        "action": "Khong can sua",
        "threat_type": None,
        "valid_end_pos": None,
        "can_trim": False,
    }

    try:
        st = fp.stat()
    except Exception as exc:
        res.update({
            "status": "ERROR",
            "reason": "Loi truy cap tep",
            "details": str(exc),
            "action": "Bo qua",
        })
        return res

    fsize = st.st_size

    # Layer 1: 0 byte file
    if fsize == 0:
        res.update({
            "status": "CORRUPTED",
            "reason": "Tep rong (0 bytes)",
            "details": "Tep tin khong chua bat ky du lieu nao",
            "action": "Khong the sua",
        })
        return res

    # Read up to 8KB for magic byte and header validation
    try:
        with open(fp, "rb") as f:
            head = f.read(min(fsize, 8192))
    except Exception as exc:
        res.update({
            "status": "ERROR",
            "reason": "Loi doc tep",
            "details": str(exc),
            "action": "Bo qua",
        })
        return res

    # Layer 1b: Damaged block (all 0x00 or all 0xFF)
    if len(head) >= 512 and (head == b'\x00' * len(head) or head == b'\xff' * len(head)):
        res.update({
            "status": "CORRUPTED",
            "reason": "Khoi hong (Null/FF block)",
            "details": "Tep chua toan bo byte 0x00 hoac 0xFF do loi o dia hoac bad dump",
            "action": "Khong the sua",
        })
        return res

    ext = fp.suffix.lower()

    # Layer 2: Disguised Executable or Dangerous Script
    if ext not in {'.exe', '.dll', '.sys', '.ocx', '.bin'} and head.startswith(b'MZ'):
        res.update({
            "status": "THREAT",
            "reason": "PE Executable tra hinh",
            "details": f"Tep duoi '{ext}' nhung header la 'MZ' (Windows PE Executable)",
            "action": "Can cach ly",
            "threat_type": "DISGUISED_PE",
        })
        return res

    if ext not in {'.elf', '.so'} and head.startswith(b'\x7fELF'):
        res.update({
            "status": "THREAT",
            "reason": "Linux ELF tra hinh",
            "details": f"Tep duoi '{ext}' nhung header la Linux ELF Binary",
            "action": "Can cach ly",
            "threat_type": "DISGUISED_ELF",
        })
        return res

    if ext in DANGEROUS_EXTENSIONS:
        res.update({
            "status": "THREAT",
            "reason": f"Script nguy hiem ({ext})",
            "details": f"Tep thuc thi script ({ext}) nam trong thu muc du lieu",
            "action": "Can cach ly",
            "threat_type": "DANGEROUS_SCRIPT",
        })
        return res

    # Layer 3: WebShell / Script Injection in Media Files
    if ext in VALID_MEDIA_EXTS:
        try:
            with open(fp, "rb") as f:
                scan_buf = f.read(min(fsize, 8 * 1024 * 1024))
            found_pats = [pat.decode('ascii', errors='ignore') for pat in MALICIOUS_SCRIPT_PATTERNS if pat in scan_buf.lower()]
            if found_pats:
                pats_str = ", ".join(found_pats[:3])
                res.update({
                    "status": "THREAT",
                    "reason": "WebShell / Script Injection",
                    "details": f"Phat hien chuoi script nguy hiem nhung trong media: {pats_str}",
                    "action": "Can cach ly",
                    "threat_type": "SCRIPT_INJECTION",
                })
                return res
        except Exception as _bare_exc:
            log_swallowed("INSPECTOR", _bare_exc, label="Bỏ qua lỗi")

    # Layer 4: Structural Integrity & Trailing Overlay Check
    # 4.1 JPEG
    if ext in ('.jpg', '.jpeg'):
        if not head.startswith(b'\xff\xd8'):
            res.update({
                "status": "CORRUPTED",
                "reason": "Sai header JPEG",
                "details": "Thieu SOI marker (FF D8)",
                "action": "Khong the sua",
            })
            return res

        try:
            with _map_file(fp) as content:
                total_len = len(content)
                eoi_idx = content.rfind(b'\xff\xd9')
                trailing_slice = content[eoi_idx + 2:eoi_idx + 2 + 4096] if eoi_idx != -1 else b""

            if eoi_idx == -1:
                res.update({
                    "status": "CORRUPTED",
                    "reason": "Mat footer EOI",
                    "details": "Thieu marker ket thuc anh (FF D9), tep bi tai dang do",
                    "action": "Khong the sua",
                })
                return res

            valid_end = eoi_idx + 2
            if total_len > valid_end:
                trailing_len = total_len - valid_end
                info = "Overlay rac"
                if trailing_slice.startswith(b'PK\x03\x04'):
                    info = "Zip/Office payload an"
                elif trailing_slice.startswith(b'Rar!'):
                    info = "Rar payload an"
                elif trailing_slice.startswith(b'MZ'):
                    info = "PE Executable an"
                elif b'<?php' in trailing_slice or b'<script' in trailing_slice:
                    info = "WebShell payload an"

                res.update({
                    "status": "OVERLAY",
                    "reason": "Du lieu thua (Trailing Overlay)",
                    "details": f"Phat hien {format_bytes(trailing_len)} sau marker EOI ({info})",
                    "action": "Co the got bo",
                    "bytes_stripped": trailing_len,
                    "valid_end_pos": valid_end,
                    "can_trim": True,
                })
                return res
        except Exception as exc:
            res.update({
                "status": "ERROR",
                "reason": "Loi doc JPEG",
                "details": str(exc),
                "action": "Bo qua",
            })
            return res

    # 4.2 PNG
    elif ext == '.png':
        if not head.startswith(b'\x89PNG\r\n\x1a\n'):
            res.update({
                "status": "CORRUPTED",
                "reason": "Sai header PNG",
                "details": "Khong khop chu ky PNG",
                "action": "Khong the sua",
            })
            return res

        try:
            pos = 8
            iend_end = None
            with _map_file(fp) as content:
                total_len = len(content)
                while pos + 8 <= total_len:
                    ch_len = struct.unpack(">I", content[pos:pos + 4])[0]
                    ch_type = content[pos + 4:pos + 8]
                    if ch_type == b'IEND':
                        iend_end = pos + 12
                        break
                    pos += 4 + 4 + ch_len + 4

            if iend_end is None:
                res.update({
                    "status": "CORRUPTED",
                    "reason": "Thieu chunk IEND",
                    "details": "Khong tim thay chunk ket thuc IEND, tep bi hong",
                    "action": "Khong the sua",
                })
                return res

            if total_len > iend_end:
                trailing_len = total_len - iend_end
                res.update({
                    "status": "OVERLAY",
                    "reason": "Du lieu thua (Trailing Overlay)",
                    "details": f"Phat hien {format_bytes(trailing_len)} sau chunk IEND",
                    "action": "Co the got bo",
                    "bytes_stripped": trailing_len,
                    "valid_end_pos": iend_end,
                    "can_trim": True,
                })
                return res
        except Exception as exc:
            res.update({
                "status": "ERROR",
                "reason": "Loi doc PNG",
                "details": str(exc),
                "action": "Bo qua",
            })
            return res

    # 4.3 WebP
    elif ext == '.webp':
        if head.startswith(b'RIFF') and len(head) >= 12 and head[8:12] == b'WEBP':
            expected_size = int.from_bytes(head[4:8], 'little') + 8
            if fsize < expected_size:
                res.update({
                    "status": "CORRUPTED",
                    "reason": "Cat cut RIFF",
                    "details": f"Dung luong {format_bytes(fsize)} < header RIFF {format_bytes(expected_size)}",
                    "action": "Khong the sua",
                })
                return res
            elif fsize > expected_size:
                trailing_len = fsize - expected_size
                res.update({
                    "status": "OVERLAY",
                    "reason": "Du lieu thua (Trailing Overlay)",
                    "details": f"Phat hien {format_bytes(trailing_len)} sau phan than RIFF",
                    "action": "Co the got bo",
                    "bytes_stripped": trailing_len,
                    "valid_end_pos": expected_size,
                    "can_trim": True,
                })
                return res

    # 4.4 GIF
    elif ext == '.gif':
        if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
            try:
                with _map_file(fp) as content:
                    total_len = len(content)
                    trailer_idx = content.rfind(b'\x3b')
                if trailer_idx != -1 and total_len > trailer_idx + 1:
                    trailing_len = total_len - (trailer_idx + 1)
                    res.update({
                        "status": "OVERLAY",
                        "reason": "Du lieu thua (Trailing Overlay)",
                        "details": f"Phat hien {format_bytes(trailing_len)} sau trailer GIF (0x3B)",
                        "action": "Co the got bo",
                        "bytes_stripped": trailing_len,
                        "valid_end_pos": trailer_idx + 1,
                        "can_trim": True,
                    })
                    return res
            except Exception as _bare_exc:
                log_swallowed("INSPECTOR", _bare_exc)

    return res


def trim_file_overlay(
    filepath: Path | str,
    valid_end_pos: Optional[int] = None,
    backup_dir: Optional[Path | str] = None,
) -> Tuple[bool, int, str]:
    """
    Trim trailing overlay from a file. If valid_end_pos is not provided, runs inspect_file first.
    The removed overlay is saved to `backup_dir` (default: <folder>/_Quarantine) first;
    if that backup fails, the file is left untouched.
    Returns (success, bytes_trimmed, message).
    """
    fp = Path(filepath)
    if valid_end_pos is None:
        insp = inspect_file(fp)
        if not insp.get("can_trim") or not insp.get("valid_end_pos"):
            return False, 0, insp.get("reason", "Khong the got bo")
        valid_end_pos = insp["valid_end_pos"]

    try:
        cur_size = fp.stat().st_size
        if cur_size <= valid_end_pos:
            return True, 0, "Tep khong co du lieu thua"

        bytes_to_trim = cur_size - valid_end_pos
        q_dir = Path(backup_dir) if backup_dir else _default_backup_dir(fp)
        try:
            saved = _save_removed_bytes(fp, valid_end_pos, cur_size, q_dir, "overlay")
        except Exception as exc:
            return False, 0, f"Khong the sao luu overlay, huy got bo: {exc}"

        if strip_trailing_data(fp, valid_end_pos):
            return True, bytes_to_trim, f"Da got bo {format_bytes(bytes_to_trim)} (sao luu: {saved.name})"

        # Only discard the backup when the file is provably untouched
        try:
            untouched = fp.stat().st_size == cur_size
        except OSError:
            untouched = False
        if untouched:
            saved.unlink(missing_ok=True)
            return False, 0, "Khong the cat du lieu tep (tep giu nguyen)"
        return False, 0, f"Khong the cat du lieu tep — ban sao luu giu tai: {saved}"
    except Exception as exc:
        return False, 0, str(exc)

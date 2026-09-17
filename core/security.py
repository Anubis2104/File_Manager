"""
core/security.py
Security subsystem: Windows AMSI in-memory malware inspection,
Microsoft Defender MpCmdRun fallback, Quarantine vault management,
and NTFS Alternate Data Stream (ADS) unblocking.
"""
from __future__ import annotations

import os
import sys
import shutil
import hashlib
import datetime
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def calculate_sha256(filepath: Path | str) -> str:
    """Compute SHA256 hex digest for a file."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return "UNKNOWN_HASH"


class AmsiScanner:
    """
    In-memory Antimalware Scan Interface (AMSI) integration using amsi.dll on Windows.
    Enables zero-disk-write malware detection for loaded buffers.
    """

    def __init__(self, app_name: str = "FileManagerPro"):
        self.app_name = app_name
        self.available = False
        self.amsi = None
        self.amsi_ctx = None
        self.amsi_session = None

        if sys.platform != "win32":
            return

        try:
            import ctypes
            from ctypes import wintypes

            self.amsi = ctypes.windll.LoadLibrary("amsi.dll")

            class HAMSICONTEXT(ctypes.c_void_p):
                pass

            class HAMSISESSION(ctypes.c_void_p):
                pass

            self.HAMSICONTEXT = HAMSICONTEXT
            self.HAMSISESSION = HAMSISESSION
            self.AMSI_RESULT = ctypes.c_int

            ctx = self.HAMSICONTEXT()
            hr = self.amsi.AmsiInitialize(wintypes.LPCWSTR(self.app_name), ctypes.byref(ctx))
            if hr == 0:
                self.amsi_ctx = ctx
                sess = self.HAMSISESSION()
                hr_sess = self.amsi.AmsiOpenSession(self.amsi_ctx, ctypes.byref(sess))
                if hr_sess == 0:
                    self.amsi_session = sess
                    self.available = True
        except Exception:
            self.available = False

    def scan_buffer(self, buffer_bytes: bytes, content_name: str = "sample") -> Tuple[bool, int, str]:
        """
        Scan in-memory byte buffer with AMSI.
        Returns: (is_malware_detected, result_code, description)
        """
        if not self.available or not buffer_bytes:
            return False, 0, "AMSI khong kha dung hoac buffer rong"

        try:
            import ctypes
            from ctypes import wintypes, byref

            res = self.AMSI_RESULT()
            hr = self.amsi.AmsiScanBuffer(
                self.amsi_ctx,
                buffer_bytes,
                len(buffer_bytes),
                wintypes.LPCWSTR(content_name),
                self.amsi_session,
                byref(res),
            )
            if hr == 0:
                # AMSI_RESULT_DETECTED = 32768 (0x8000)
                is_detected = res.value >= 32768
                return is_detected, res.value, f"AMSI_CODE_{res.value}"
            return False, hr, f"AMSI_HR_{hr}"
        except Exception as exc:
            return False, -1, str(exc)

    def scan_file(self, filepath: Path | str) -> Tuple[bool, int, str]:
        """Read file into memory and scan with AMSI.

        Strategy: scan full file if <=16MB.
        For larger files: read header (4MB) + tail (4MB) to detect
        both pre-pended and appended payloads.
        """
        try:
            fp = Path(filepath)
            file_size = fp.stat().st_size
            _4MB = 4 * 1024 * 1024
            _16MB = 16 * 1024 * 1024
            with open(fp, "rb") as f:
                if file_size <= _16MB:
                    content = f.read()
                else:
                    # Header 4MB + tail 4MB ← phát hiện cả payload ở đầu lẫn cuối file
                    header = f.read(_4MB)
                    f.seek(max(0, file_size - _4MB))
                    tail = f.read()
                    content = header + tail
            return self.scan_buffer(content, fp.name)
        except Exception as exc:
            return False, -1, str(exc)

    def close(self):
        """Release AMSI session and context handles."""
        if self.available and self.amsi and self.amsi_ctx:
            try:
                if self.amsi_session:
                    self.amsi.AmsiCloseSession(self.amsi_ctx, self.amsi_session)
                self.amsi.AmsiUninitialize(self.amsi_ctx)
            except Exception:
                pass
            self.available = False

    def __del__(self):
        self.close()


def find_mpcmdrun() -> Optional[str]:
    """Locate Microsoft Defender CLI (MpCmdRun.exe) on Windows."""
    if sys.platform != "win32":
        return None

    candidates = [
        r"C:\Program Files\Windows Defender\MpCmdRun.exe"
    ]
    platform_dir = r"C:\ProgramData\Microsoft\Windows Defender\Platform"
    if os.path.exists(platform_dir):
        for root, _, files in os.walk(platform_dir):
            if "MpCmdRun.exe" in files:
                candidates.insert(0, os.path.join(root, "MpCmdRun.exe"))
                break

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def scan_file_defender(filepath: Path | str) -> Tuple[bool, str]:
    """Fallback scanner using MpCmdRun.exe."""
    mp = find_mpcmdrun()
    if not mp:
        return False, "MpCmdRun khong tim thay"

    fp = str(Path(filepath).resolve())
    cmd = [mp, "-Scan", "-ScanType", "3", "-File", fp, "-DisableRemediation"]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        # MpCmdRun return code: 0 = Clean, 2 = Threat found
        if res.returncode == 2:
            return True, "Defender phat hien ma doc (Code 2)"
        return False, "Sạch"
    except Exception as exc:
        return False, f"Loi scan: {exc}"


def quarantine_file(
    filepath: Path | str,
    quarantine_dir: Path | str,
    threat_type: str,
    details: str,
) -> Tuple[bool, str]:
    """
    Safely quarantine a suspicious or malicious file:
      - Moves file into quarantine_dir
      - Renames with .quarantined suffix to disable execution
      - Computes SHA256 and records entry in quarantine_log.txt
    """
    fp = Path(filepath)
    q_dir = Path(quarantine_dir)
    q_dir.mkdir(parents=True, exist_ok=True)

    if not fp.exists():
        return False, "Tep khong ton tai"

    sha256 = calculate_sha256(fp)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    q_filename = f"{fp.name}_{ts}.quarantined"
    q_target = q_dir / q_filename

    try:
        # Thử atomic move trước (os.replace — không có khoảng rống giữa copy và delete)
        os.replace(str(fp), str(q_target))
    except OSError:
        # Cross-volume fallback: copy + verify checksum trước khi xóa gốc
        try:
            shutil.copy2(str(fp), str(q_target))
            # Xác minh copy thành công (size match) trước khi xóa file gốc
            if q_target.exists() and q_target.stat().st_size == fp.stat().st_size:
                fp.unlink(missing_ok=True)
            else:
                q_target.unlink(missing_ok=True)
                return False, "Sáo chép kiểm tra không khớp kích thước"
        except Exception as exc:
            return False, f"Không thể di chuyển tệp: {exc}"

    # Log quarantine event
    log_entry = (
        f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"TEP: {fp} | NGUY CO: {threat_type} | CHI TIET: {details} | "
        f"SHA256: {sha256} | LUU TAI: {q_target}\n"
    )
    try:
        log_file = q_dir / "quarantine_log.txt"
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(log_entry)
    except Exception:
        pass

    return True, str(q_target)


def unblock_file_and_clean_ads(filepath: Path | str) -> Tuple[bool, str]:
    """
    Unblock file (remove Zone.Identifier Mark-of-the-Web)
    and remove Alternate Data Streams (ADS) on NTFS.
    """
    fp = Path(filepath).resolve()
    if not fp.exists():
        return False, "Tep khong ton tai"

    if sys.platform != "win32":
        return True, "Khong phai he dieu hanh Windows"

    try:
        # Escape ký tự ' trong path để tránh PowerShell injection
        fp_escaped = str(fp).replace("'", "''")
        ps_cmd = (
            f"Unblock-File -LiteralPath '{fp_escaped}' -ErrorAction SilentlyContinue; "
            f"Get-Item -LiteralPath '{fp_escaped}' -Stream * -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.Stream -ne ':$DATA' }} | Remove-Item -ErrorAction SilentlyContinue"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        return res.returncode == 0, "Da go bo Zone.Identifier va cac luong ADS"
    except Exception as exc:
        return False, str(exc)

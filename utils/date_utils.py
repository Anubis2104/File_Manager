"""
utils/date_utils.py
Normalize and extract creation dates from EXIF, video metadata, or file system.
Priority order: EXIF DateTimeOriginal > DateTimeDigitized > Video creation_time
                > File birthtime (Windows) > File mtime.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from utils.safe_log import log_swallowed, safe_log


# EXIF date string format: "2024:08:19 10:30:00"
_EXIF_DATE_RE = re.compile(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")


def parse_exif_date(value: str) -> Optional[datetime]:
    """Parse EXIF date string like '2024:08:19 10:30:00'."""
    m = _EXIF_DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()))
    except ValueError:
        return None


def get_file_birthtime(path: Path) -> Optional[datetime]:
    """Get file creation time (st_birthtime on Windows/Mac, st_mtime fallback)."""
    try:
        stat = path.stat()
        # Windows: st_ctime is creation time
        if os.name == "nt":
            return datetime.fromtimestamp(stat.st_ctime)
        # POSIX: st_birthtime if available (macOS), else mtime
        if hasattr(stat, "st_birthtime"):
            return datetime.fromtimestamp(stat.st_birthtime)
        return datetime.fromtimestamp(stat.st_mtime)
    except OSError:
        return None


def _test_exiftool_binary(exe_path: str) -> bool:
    """Check if the given exiftool executable actually runs without error."""
    if not exe_path or not Path(exe_path).is_file():
        return False
    try:
        r = subprocess.run(
            [exe_path, "-ver"],
            capture_output=True, text=True, timeout=4,
            encoding="utf-8", errors="replace",
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def resolve_exiftool_exe(preferred: str = "exiftool") -> str:
    """Find a verified working exiftool executable on system, project root, or standard paths."""
    if preferred and _test_exiftool_binary(preferred):
        return str(Path(preferred).resolve())

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    try:
        from utils.file_utils import get_app_dir
        app_dir = get_app_dir()
    except Exception:
        app_dir = Path(__file__).resolve().parent.parent

    candidates = [
        app_dir / "ExifTool.exe",
        app_dir / "exiftool.exe",
        Path.cwd() / "ExifTool.exe",
        Path.cwd() / "exiftool.exe",
        Path(__file__).parent.parent / "exiftool.exe",
        Path(local_app_data) / "Programs" / "ExifTool" / "ExifTool.exe" if local_app_data else None,
        Path(r"C:\Tools\ExifTool\exiftool.exe"),
        Path(r"C:\Program Files\ExifTool\exiftool.exe"),
    ]
    for c in candidates:
        if c and _test_exiftool_binary(str(c)):
            return str(c.resolve())

    which = shutil.which(preferred)
    if which and _test_exiftool_binary(which):
        return which

    for c in candidates:
        if c and c.is_file():
            return str(c.resolve())

    return preferred


_resolve_exiftool = resolve_exiftool_exe


def run_exiftool_utf8(
    exiftool_exe: str,
    args: list[str],
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """
    Run ExifTool using a temporary UTF-8 argfile (-@) to ensure 100% reliability on Windows.
    Bypasses Windows ANSI command-line encoding issues with Unicode/CJK/accented characters
    and paths containing square brackets [ ] or wildcards.
    """
    import tempfile
    exiftool_cmd = resolve_exiftool_exe(exiftool_exe)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt") as tf:
        for a in args:
            tf.write(f"{a}\n")
        tmp_name = tf.name

    try:
        cmd = [exiftool_cmd, "-charset", "filename=utf8", "-@", tmp_name]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except Exception as _bare_exc:
                safe_log("w", "DATE_UTILS", f"Khong xoa temp argfile: {_bare_exc}")


def get_date_from_exiftool(path: Path, exiftool_exe: str = "exiftool") -> Optional[datetime]:
    """
    Use ExifTool to extract the best available creation date.
    Returns None if ExifTool is not installed or no date found.
    """
    exiftool_cmd = _resolve_exiftool(exiftool_exe)
    try:
        result = run_exiftool_utf8(
            exiftool_cmd,
            [
                "-j",                      # JSON output
                "-DateTimeOriginal",
                "-DateTimeDigitized",
                "-CreateDate",
                "-MediaCreateDate",
                "-TrackCreateDate",
                "-QuickTime:CreateDate",
                str(path),
            ],
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        data = json.loads(result.stdout)
        if not data:
            return None
        record = data[0]

        priority_keys = [
            "DateTimeOriginal",
            "DateTimeDigitized",
            "CreateDate",
            "MediaCreateDate",
            "TrackCreateDate",
            "QuickTime:CreateDate",
        ]
        for key in priority_keys:
            val = record.get(key, "")
            if val and not val.startswith("0000"):
                dt = parse_exif_date(str(val))
                if dt and dt.year > 1970:
                    return dt
        return None

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def get_date_from_pillow(path: Path) -> Optional[datetime]:
    """Fast in-memory EXIF date extraction using Pillow (<1ms, no subprocess)."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img._getexif()
            if not exif:
                return None
            # DateTimeOriginal (36867), DateTimeDigitized (36868), DateTime (306)
            for tag_id in (36867, 36868, 306):
                val = exif.get(tag_id)
                if val and isinstance(val, str) and not val.startswith("0000"):
                    dt = parse_exif_date(val)
                    if dt and dt.year > 1970:
                        return dt
    except Exception as _bare_exc:
        log_swallowed("DATE_UTILS", _bare_exc)
    return None


def get_date_from_mutagen(path: Path) -> Optional[datetime]:
    """Fast in-memory video metadata date extraction using mutagen (<1ms)."""
    try:
        import mutagen
        f = mutagen.File(str(path))
        if f and hasattr(f, "tags") and f.tags:
            for key in ("\xa9day", "creation_time", "date"):
                if key in f.tags:
                    val = str(f.tags[key][0])
                    val_clean = val.replace("Z", "").replace("T", " ")[:19]
                    try:
                        return datetime.fromisoformat(val_clean)
                    except Exception as _bare_exc:
                        log_swallowed("DATE_UTILS", _bare_exc)
    except Exception as _bare_exc:
        log_swallowed("DATE_UTILS", _bare_exc)
    return None


def extract_best_date(
    path: Path,
    exiftool_exe: str = "exiftool",
) -> tuple[Optional[datetime], str]:
    """
    Extract the best creation date from a file, using ultra-fast priority order:
      1. Fast in-memory Pillow/piexif EXIF (< 1ms, no subprocess)
      2. Fast in-memory video metadata (< 1ms, no subprocess)
      3. File birthtime (Windows st_ctime) (< 0.01ms)
      4. ExifTool subprocess (fallback only if needed)
      5. File mtime

    Returns:
        (datetime_or_None, source_string)
        source_string: 'exif' | 'birthtime' | 'mtime' | 'unknown'
    """
    ext = path.suffix.lower()

    # 1. Fast in-memory EXIF for images
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".heic", ".heif", ".dng"):
        dt = get_date_from_pillow(path)
        if dt:
            return dt, "exif"

    # 2. Fast in-memory metadata for videos
    if ext in (".mp4", ".mov", ".m4v", ".3gp"):
        dt = get_date_from_mutagen(path)
        if dt:
            return dt, "exif"

    # 3. Fast ExifTool for RAW camera formats & complex video containers only
    raw_and_complex_exts = {
        ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".pef", ".raf",
        ".mkv", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m2ts"
    }
    if ext in raw_and_complex_exts:
        dt = get_date_from_exiftool(path, exiftool_exe)
        if dt:
            return dt, "exif"

    # 4. File birthtime (Windows creation time: <0.01ms, ultra fast)
    dt = get_file_birthtime(path)
    if dt and dt.year > 1970:
        source = "birthtime" if os.name == "nt" else "mtime"
        return dt, source

    # 5. ExifTool last-resort fallback for standard images without Pillow EXIF tags
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".heic", ".heif"):
        dt = get_date_from_exiftool(path, exiftool_exe)
        if dt:
            return dt, "exif"

    # 5. File mtime
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime and mtime.year > 1970:
            return mtime, "mtime"
    except Exception as _bare_exc:
        log_swallowed("DATE_UTILS", _bare_exc)

    return None, "unknown"


def format_date_for_rename(dt: datetime, fmt: str = "DDMMYY") -> str:
    """
    Format a datetime for use in rename strings.
    fmt: 'DDMMYY' → '190826'
         'YYYYMMDD' → '20260819'
         'DDMMYYYY' → '19082026'
    """
    mapping = {
        "DDMMYY":   f"{dt.day:02d}{dt.month:02d}{str(dt.year)[2:]}",
        "DDMMYYYY": f"{dt.day:02d}{dt.month:02d}{dt.year:04d}",
        "YYYYMMDD": f"{dt.year:04d}{dt.month:02d}{dt.day:02d}",
        "MMDDYY":   f"{dt.month:02d}{dt.day:02d}{str(dt.year)[2:]}",
    }
    return mapping.get(fmt, mapping["DDMMYY"])

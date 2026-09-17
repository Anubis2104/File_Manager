"""
core/metadata.py
Read, preserve, and strip EXIF/video metadata using ExifTool.
Key features:
  - "safe date store": preserve creation date before wiping metadata.
  - ArgfileMetadataEngine: batch ExifTool via argfile (150-300 files/chunk),
    multi-namespace tag rewrite, single-file fallback on chunk error.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.date_utils import (
    extract_best_date, parse_exif_date, format_date_for_rename,
    resolve_exiftool_exe, _test_exiftool_binary, run_exiftool_utf8
)


FFMPEG_CONTAINER_EXTS: frozenset[str] = frozenset({
    ".mkv", ".webm", ".mka", ".mks", ".avi"
})

_RESOLVED_FFMPEG: Optional[str] = None


def resolve_ffmpeg_exe(custom_exe: str = "ffmpeg") -> str:
    """Find a functional ffmpeg binary from system PATH, project directory, or winget."""
    global _RESOLVED_FFMPEG
    if _RESOLVED_FFMPEG:
        return _RESOLVED_FFMPEG

    import shutil
    candidates = [
        custom_exe,
        "ffmpeg",
        str(Path(__file__).parent.parent / "ffmpeg.exe"),
        str(Path(__file__).parent.parent / "utils" / "ffmpeg.exe"),
        r"C:\Tools\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if not c:
            continue
        which_path = shutil.which(c)
        if which_path and os.path.isfile(which_path):
            _RESOLVED_FFMPEG = which_path
            return which_path
        if os.path.isfile(c):
            _RESOLVED_FFMPEG = str(Path(c).resolve())
            return _RESOLVED_FFMPEG

    _RESOLVED_FFMPEG = "ffmpeg"
    return "ffmpeg"


def strip_video_metadata_with_ffmpeg(filepath: Path | str, ffmpeg_exe: Optional[str] = None) -> tuple[bool, str]:
    """
    Xóa toàn bộ metadata của video (MKV, WebM, AVI...) bằng FFmpeg stream copy (-c copy).
    Không nén lại video/audio (100% lossless), tốc độ cực nhanh.
    Bảo toàn thuộc tính file và thay thế nguyên tử (atomic replace).
    """
    fp = Path(filepath)
    if not fp.is_file():
        return False, "Tệp tin không tồn tại"

    bin_path = ffmpeg_exe or resolve_ffmpeg_exe()
    temp_out = fp.with_name(f"{fp.stem}_tmp_strip{fp.suffix}")

    cmd = [
        bin_path,
        "-y",
        "-i", str(fp),
        "-map", "0",
        "-c", "copy",
        "-map_metadata", "-1",
        "-map_metadata:s", "-1",
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        str(temp_out),
    ]

    try:
        stat = fp.stat()
        orig_atime = stat.st_atime
        orig_mtime = stat.st_mtime

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 0:
            os.replace(temp_out, fp)
            try:
                os.utime(fp, (orig_atime, orig_mtime))
            except Exception:
                pass
            return True, ""
        else:
            if temp_out.exists():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            err = res.stderr.strip() or "Lỗi FFmpeg không xác định"
            return False, err
    except Exception as exc:
        if temp_out.exists():
            try:
                temp_out.unlink()
            except Exception:
                pass
        return False, str(exc)


def write_video_metadata_with_ffmpeg(
    filepath: Path | str,
    tags: Optional[dict[str, str]] = None,
    dt: Optional[datetime] = None,
    strip_existing: bool = False,
    ffmpeg_exe: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Ghi metadata hoặc ngày tạo vào container video (MKV, WebM, AVI...) bằng FFmpeg stream copy.
    """
    fp = Path(filepath)
    if not fp.is_file():
        return False, "Tệp tin không tồn tại"

    bin_path = ffmpeg_exe or resolve_ffmpeg_exe()
    temp_out = fp.with_name(f"{fp.stem}_tmp_write{fp.suffix}")
    tags = tags or {}

    cmd = [
        bin_path,
        "-y",
        "-i", str(fp),
        "-map", "0",
        "-c", "copy",
    ]

    if strip_existing:
        cmd.extend(["-map_metadata", "-1", "-map_metadata:s", "-1"])

    artist = tags.get("Artist") or tags.get("artist") or tags.get("Author")
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])

    title = tags.get("Title") or tags.get("title")
    if title:
        cmd.extend(["-metadata", f"title={title}"])

    copyright_val = tags.get("Copyright") or tags.get("copyright")
    if copyright_val:
        cmd.extend(["-metadata", f"copyright={copyright_val}"])

    comment = tags.get("UserComment") or tags.get("comment") or tags.get("Description")
    if comment:
        cmd.extend(["-metadata", f"comment={comment}"])

    if dt:
        dt_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
        cmd.extend(["-metadata", f"creation_time={dt_iso}"])

    cmd.append(str(temp_out))

    try:
        stat = fp.stat()
        orig_atime = stat.st_atime
        orig_mtime = dt.timestamp() if dt else stat.st_mtime

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 0:
            os.replace(temp_out, fp)
            try:
                os.utime(fp, (orig_atime, orig_mtime))
            except Exception:
                pass
            return True, ""
        else:
            if temp_out.exists():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            err = res.stderr.strip() or "Lỗi FFmpeg không xác định"
            return False, err
    except Exception as exc:
        if temp_out.exists():
            try:
                temp_out.unlink()
            except Exception:
                pass
        return False, str(exc)





def strip_jpeg_lossless_in_ram(filepath: Path | str, preserve_icc: bool = True) -> tuple[bool, str]:
    """
    Xóa toàn bộ metadata APP markers (EXIF, XMP, IPTC, COM) cho JPEG trực tiếp trong RAM.
    Không nén lại ảnh, bảo toàn 100% chất lượng pixel và ICC Profile (Color Space).
    """
    import io
    import struct

    fp = Path(filepath)
    try:
        with open(fp, "rb") as f:
            data = f.read()

        if not data.startswith(b'\xff\xd8'):
            return False, "Khong phai header JPEG hop le"

        out = io.BytesIO()
        out.write(b'\xff\xd8')
        pos = 2
        length = len(data)

        while pos < length:
            if data[pos] != 0xff:
                break
            marker = data[pos + 1]
            pos += 2

            if marker in (0xd8, 0xd9) or (0xd0 <= marker <= 0xd7):
                out.write(bytes([0xff, marker]))
                continue

            if marker == 0xda:  # Start of Scan (SOS) -> phan con lai la du lieu anh thuc
                out.write(bytes([0xff, marker]))
                out.write(data[pos:])
                break

            if pos + 2 > length:
                break
            seg_len = struct.unpack(">H", data[pos:pos + 2])[0]
            seg_data = data[pos + 2:pos + seg_len]

            # 0xE1 (EXIF/XMP), 0xED (IPTC/Photoshop), 0xFE (Comment)
            if marker in (0xe1, 0xed, 0xfe):
                pos += seg_len
                continue

            # APP2: Giu lai ICC Profile neu co, xoa cac payload khac
            if marker == 0xe2:
                if preserve_icc and seg_data.startswith(b'ICC_PROFILE\x00'):
                    out.write(bytes([0xff, marker]))
                    out.write(data[pos:pos + seg_len])
                pos += seg_len
                continue

            # APP0: Giu lai JFIF/JFXX chuan
            if marker == 0xe0:
                if seg_data.startswith(b'JFIF\x00') or seg_data.startswith(b'JFXX\x00'):
                    out.write(bytes([0xff, marker]))
                    out.write(data[pos:pos + seg_len])
                pos += seg_len
                continue

            # Giu nguyen cac marker cau truc khac (SOF, DQT, DHT, DRI...)
            out.write(bytes([0xff, marker]))
            out.write(data[pos:pos + seg_len])
            pos += seg_len

        clean_bytes = out.getvalue()
        if len(clean_bytes) > 2:
            with open(fp, "wb") as f:
                f.write(clean_bytes)
            return True, ""
        return False, "Loi cau truc JPEG khi tao du lieu sach"
    except Exception as exc:
        return False, str(exc)


def strip_png_lossless_in_ram(filepath: Path | str) -> tuple[bool, str]:
    """
    Xóa toàn bộ các chunk metadata (tEXt, zTXt, iTXt, eXIf) cho PNG trực tiếp trong RAM.
    Bảo toàn nguyên vẹn IDAT (pixel data), PLTE, IHDR và Color Profile.
    """
    import io
    import struct

    fp = Path(filepath)
    try:
        with open(fp, "rb") as f:
            data = f.read()

        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return False, "Khong phai header PNG hop le"

        out = io.BytesIO()
        out.write(b'\x89PNG\r\n\x1a\n')

        strip_chunks = {b'tEXt', b'zTXt', b'iTXt', b'eXIf'}
        pos = 8
        total_len = len(data)

        while pos + 8 <= total_len:
            ch_len = struct.unpack(">I", data[pos:pos + 4])[0]
            ch_type = data[pos + 4:pos + 8]
            chunk_full_len = 4 + 4 + ch_len + 4

            if pos + chunk_full_len > total_len:
                break

            if ch_type not in strip_chunks:
                out.write(data[pos:pos + chunk_full_len])

            if ch_type == b'IEND':
                break

            pos += chunk_full_len

        clean_bytes = out.getvalue()
        if len(clean_bytes) > 8:
            with open(fp, "wb") as f:
                f.write(clean_bytes)
            return True, ""
        return False, "Loi cau truc PNG khi tao du lieu sach"
    except Exception as exc:
        return False, str(exc)


class MetadataEngine:
    """
    Handles all metadata operations.

    Safe-wipe flow:
        1. extract_best_date()          → get original creation date
        2. strip_metadata()             → exiftool -all= -overwrite_original
        3. restore_date_to_exif()       → write DateTimeOriginal back
        → Loop this as many times as desired; date stays unchanged.
    """

    def __init__(self, exiftool_exe: str = "exiftool"):
        self.exiftool_exe = resolve_exiftool_exe(exiftool_exe)
        self._exiftool_available: Optional[bool] = None

    # ─────────────────────────────────────────────
    # ExifTool availability check
    # ─────────────────────────────────────────────

    def is_exiftool_available(self) -> bool:
        if self._exiftool_available is not None:
            return self._exiftool_available
        self.exiftool_exe = resolve_exiftool_exe(self.exiftool_exe)
        try:
            r = subprocess.run(
                [self.exiftool_exe, "-ver"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            self._exiftool_available = r.returncode == 0
        except (FileNotFoundError, OSError):
            self._exiftool_available = False
        return self._exiftool_available

    # ─────────────────────────────────────────────
    # Read metadata
    # ─────────────────────────────────────────────

    def _read_fallback(self, path: Path) -> dict:
        """In-memory fallback to extract EXIF and file metadata via Pillow and mutagen."""
        data: dict = {}
        try:
            stat = path.stat()
            data["File:FileName"] = path.name
            data["File:FileSize"] = f"{stat.st_size / 1024:.1f} KB" if stat.st_size < 1048576 else f"{stat.st_size / 1048576:.2f} MB"
            data["File:FileModifyDate"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            pass

        # Try Pillow for images
        try:
            from PIL import Image, ExifTags
            Image.MAX_IMAGE_PIXELS = 256 * 1024 * 1024  # ← 256MP (8K×8K) giới hạn an toàn, tránh OOM
            with Image.open(path) as img:
                data["File:FileType"] = img.format or path.suffix.upper().lstrip(".")
                data["File:ImageWidth"] = img.width
                data["File:ImageHeight"] = img.height
                raw_exif = img.getexif()
                if raw_exif:
                    for tag_id, val in raw_exif.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                        data[f"EXIF:{tag_name}"] = str(val)
                    for ifd_id in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
                        try:
                            ifd = raw_exif.get_ifd(ifd_id)
                            for sub_id, sub_val in ifd.items():
                                sub_name = ExifTags.TAGS.get(sub_id, str(sub_id))
                                data[f"EXIF:{sub_name}"] = str(sub_val)
                        except Exception:
                            pass
        except Exception:
            pass

        # Try mutagen for audio/video
        if not any(k.startswith("EXIF:") for k in data):
            try:
                import mutagen
                mf = mutagen.File(str(path))
                if mf and mf.info:
                    if hasattr(mf.info, "length") and mf.info.length:
                        m, s = divmod(int(mf.info.length), 60)
                        data["Media:Duration"] = f"{m:02d}:{s:02d}"
                    if hasattr(mf.info, "bitrate") and mf.info.bitrate:
                        data["Media:Bitrate"] = f"{mf.info.bitrate // 1000} kbps"
                if mf and mf.tags:
                    for k, v in mf.tags.items():
                        data[f"Tag:{k}"] = str(v)
            except Exception:
                pass

        return data

    def _run_exiftool(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run ExifTool using UTF-8 argfile to handle Unicode/CJK and brackets safely on Windows."""
        return run_exiftool_utf8(self.exiftool_exe, args, timeout=timeout)

    def read_all(self, path: Path) -> dict:
        """Return all metadata tags as a flat dict via ExifTool JSON with graceful in-memory fallback."""
        from core.app_logcat import logcat
        t0 = time.time()
        if self.is_exiftool_available():
            try:
                r = self._run_exiftool(["-j", "-G", str(path)], timeout=15)
                if r.returncode == 0 and r.stdout.strip():
                    data = json.loads(r.stdout)
                    if data and isinstance(data, list) and len(data) > 0:
                        dur = (time.time() - t0) * 1000
                        logcat.d("CORE:ExifTool", f"Đọc metadata ExifTool cho {path.name}: {len(data[0])} thẻ ({dur:.1f}ms)")
                        return data[0]
            except Exception as e:
                logcat.w("CORE:ExifTool", f"Lỗi gọi ExifTool cho {path.name}: {e}. Sử dụng in-memory fallback.")
        data = self._read_fallback(path)
        dur = (time.time() - t0) * 1000
        logcat.d("CORE:Metadata", f"Đọc metadata fallback cho {path.name}: {len(data)} thẻ ({dur:.1f}ms)")
        return data

    def get_creation_date(self, path: Path) -> tuple[Optional[datetime], str]:
        """
        Convenience wrapper: return (datetime, source).
        source: 'exif' | 'birthtime' | 'mtime' | 'unknown'
        """
        return extract_best_date(path, self.exiftool_exe)

    # ─────────────────────────────────────────────
    # Strip metadata (safe — date is preserved)
    # ─────────────────────────────────────────────

    def strip_metadata(self, path: Path) -> tuple[bool, str]:
        """
        Remove all metadata from file.
        Fast-path: in-memory lossless stripper for JPEG/PNG (super fast, no re-encoding).
        Heavy-path: ExifTool for video, RAW, and other media containers.
        """
        ext = path.suffix.lower()
        if ext in ('.jpg', '.jpeg'):
            ok, err = strip_jpeg_lossless_in_ram(path)
            if ok:
                return True, ""
            # Neu loi in-ram thi fallback xuong ben duoi

        elif ext == '.png':
            ok, err = strip_png_lossless_in_ram(path)
            if ok:
                return True, ""
            # Fallback sang ben duoi neu can

        elif ext in FFMPEG_CONTAINER_EXTS:
            ok, err = strip_video_metadata_with_ffmpeg(path)
            if ok:
                return True, ""

        if not self.is_exiftool_available():
            return False, "ExifTool not found and file cannot be stripped in RAM/FFmpeg."
        try:
            r = self._run_exiftool(
                [
                    "-all=",              # Remove all metadata
                    "-overwrite_original",# Don't create _original backup
                    str(path),
                ],
                timeout=30,
            )
            if r.returncode == 0:
                return True, ""
            return False, r.stderr.strip()
        except Exception as exc:
            return False, str(exc)

    def restore_date_to_metadata(self, path: Path, dt: datetime) -> tuple[bool, str]:
        """
        Write creation date back into a file after metadata wipe.
        Supports both image EXIF tags, video QuickTime/Track/Media atoms, and MKV/WebM containers.
        """
        ext = path.suffix.lower()
        if ext in FFMPEG_CONTAINER_EXTS:
            return write_video_metadata_with_ffmpeg(path, tags={}, dt=dt)

        if not self.is_exiftool_available():
            # Fallback: still preserve filesystem timestamp
            try:
                ts = dt.timestamp()
                os.utime(path, (ts, ts))
            except Exception:
                pass
            return False, "ExifTool not found."

        from utils.file_utils import classify_extension
        media_type = classify_extension(path.suffix)
        dt_str = dt.strftime("%Y:%m:%d %H:%M:%S")

        args = [
            "-overwrite_original",
        ]
        if media_type == "video":
            # Video atoms
            args.extend([
                f"-QuickTime:CreateDate={dt_str}",
                f"-QuickTime:ModifyDate={dt_str}",
                f"-TrackCreateDate={dt_str}",
                f"-TrackModifyDate={dt_str}",
                f"-MediaCreateDate={dt_str}",
                f"-MediaModifyDate={dt_str}",
                f"-Keys:CreationDate={dt_str}",
            ])
        else:
            # Image EXIF
            args.extend([
                f"-DateTimeOriginal={dt_str}",
                f"-DateTimeDigitized={dt_str}",
                f"-CreateDate={dt_str}",
                f"-ModifyDate={dt_str}",
            ])

        args.append(str(path))
        try:
            r = self._run_exiftool(args, timeout=30)
            # Sync filesystem timestamps
            try:
                ts = dt.timestamp()
                os.utime(path, (ts, ts))
            except Exception:
                pass

            if r.returncode == 0:
                return True, ""
            return False, r.stderr.strip()
        except Exception as exc:
            return False, str(exc)

    def restore_date_to_exif(self, path: Path, dt: datetime) -> tuple[bool, str]:
        """Backward-compatible alias for restore_date_to_metadata."""
        return self.restore_date_to_metadata(path, dt)

    def safe_strip(self, path: Path) -> tuple[bool, Optional[datetime], str]:
        """
        Full safe-wipe pipeline:
          1. Extract original creation date
          2. Strip all metadata (GPS, camera/author/device tracking info)
          3. Restore original creation date back to container
        Returns: (success, preserved_datetime, error_message)
        """
        # Step 1: extract date
        dt, source = self.get_creation_date(path)

        # Step 2: strip all metadata
        ok, err = self.strip_metadata(path)
        if not ok:
            return False, dt, err

        # Step 3: restore date (only if we have one)
        if dt:
            ok2, err2 = self.restore_date_to_metadata(path, dt)
            if not ok2:
                # Strip đã thành công — đây là WARNING, không phải FAIL.
                # Trả về (True, dt, warning) để UI hiển thị ✅ với cảnh báo thay vì ❌.
                return True, dt, f"[WARNING] Date restore failed: {err2}"

        return True, dt, ""

    # ─────────────────────────────────────────────
    # Batch operations
    # ─────────────────────────────────────────────

    def batch_safe_strip(
        self,
        paths: list[Path],
        on_progress: Optional[callable] = None,
    ) -> list[dict]:
        """
        Safe-strip a list of files.
        Returns list of result dicts: {path, success, date, error}
        """
        results = []
        for i, path in enumerate(paths):
            ok, dt, err = self.safe_strip(path)
            results.append({"path": path, "success": ok, "date": dt, "error": err})
            if on_progress:
                on_progress(i + 1, len(paths), path)
        return results


# ─────────────────────────────────────────────────────────────────────────────
# ArgfileMetadataEngine — ExifTool Argfile Batch Engine
# ─────────────────────────────────────────────────────────────────────────────

class ArgfileMetadataEngine:
    """
    High-throughput ExifTool wrapper that submits commands via a temporary
    UTF-8 argfile (one argument per line) to avoid Windows CMD-line length
    limits and allow processing 150-300 files per ExifTool invocation.

    Tag rewrite covers all known namespaces:
        EXIF | XMP-dc | QuickTime | Keys | UserData | IPTC
    so that Artist, Copyright, and UserComment are written regardless of
    whether the container is JPEG, TIFF, MP4, MOV, MKV, or any RAW format.

    On chunk failure the engine falls back to single-file mode to isolate
    the corrupt/locked file without dropping the entire batch.
    """

    def __init__(self, exiftool_exe: str = "exiftool"):
        self.exiftool_exe = resolve_exiftool_exe(exiftool_exe)

    # ─────────────────────────────────────────────
    # Internal: argfile runner
    # ─────────────────────────────────────────────

    def _run_argfile(self, args: List[str], timeout: int = 120) -> Tuple[bool, str]:
        """
        Write args to a temp UTF-8 file and run ExifTool with '-@ <argfile>'.
        Each element in args becomes one line in the argfile.
        """
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                suffix=".txt",
            ) as tf:
                for arg in args:
                    tf.write(f"{arg}\n")
                tmp_path = tf.name

            cmd = [
                self.exiftool_exe,
                "-charset", "filename=utf8",
                "-@", tmp_path,
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return res.returncode == 0, res.stdout
        except subprocess.TimeoutExpired:
            return False, "TimeoutExpired"
        except Exception as exc:
            return False, str(exc)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    # ─────────────────────────────────────────────
    # Public: batch metadata scan
    # ─────────────────────────────────────────────

    def scan_tags_batch(
        self,
        files: List[Path],
        chunk_size: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        Read metadata from all files in chunks of chunk_size using ExifTool JSON output.
        Returns a flat list of metadata dicts (one per file, keyed by 'SourceFile').
        """
        all_meta: List[Dict[str, Any]] = []

        for i in range(0, len(files), chunk_size):
            chunk = files[i : i + chunk_size]
            args = [
                "-j", "-fast2",
                "-Artist", "-Creator", "-Author", "-By-line",
                "-QuickTime:Artist", "-Keys:Artist", "-UserData:Artist",
                "-XMP-dc:Creator",
                "-Copyright", "-Rights",
                "-QuickTime:Copyright", "-Keys:Copyright", "-UserData:Copyright",
                "-XMP-dc:Rights",
                "-UserComment", "-Description", "-Comment",
                "-QuickTime:Comment", "-Keys:Description",
                "-UserData:Description", "-XMP-dc:Description",
                "-CreateDate", "-DateTimeOriginal", "-MediaCreateDate",
                "-ImageWidth", "-ImageHeight",
                "-SourceImageWidth", "-SourceImageHeight",
                "-Rotation",
            ] + [str(p.resolve()) for p in chunk]

            ok, stdout = self._run_argfile(args, timeout=60)
            if ok and stdout:
                try:
                    all_meta.extend(json.loads(stdout))
                except Exception:
                    pass

        return all_meta

    # ─────────────────────────────────────────────
    # Public: batch tag rewrite
    # ─────────────────────────────────────────────

    def rewrite_tags_batch(
        self,
        files: List[Path],
        tags: Dict[str, str],
        strip_existing: bool = False,
        chunk_size: int = 150,
    ) -> int:
        """
        Write Artist, Copyright, and UserComment tags across all metadata
        namespaces for every file in the list.

        Args:
            files:          List of Path objects to process.
            tags:           Dict with keys 'Artist', 'Copyright', 'UserComment'.
            strip_existing: If True, wipe all existing tags first (-all:all=).
            chunk_size:     Files per ExifTool invocation (default 150).

        Returns:
            Number of files successfully updated.
        """
        from utils.file_utils import ensure_writable

        updated = 0

        # Separate FFmpeg-handled containers (MKV, WebM, AVI) from ExifTool files
        exiftool_files: List[Path] = []
        for f in files:
            ensure_writable(f)
            if f.suffix.lower() in FFMPEG_CONTAINER_EXTS:
                ok, _ = write_video_metadata_with_ffmpeg(f, tags=tags, strip_existing=strip_existing)
                if ok:
                    updated += 1
            else:
                exiftool_files.append(f)

        for i in range(0, len(exiftool_files), chunk_size):
            chunk = exiftool_files[i : i + chunk_size]
            base_args = self._build_write_args(tags, strip_existing)
            chunk_args = base_args + [str(p.resolve()) for p in chunk]

            ok, _ = self._run_argfile(chunk_args, timeout=90)
            if ok:
                updated += len(chunk)
            else:
                # Fallback: single-file to isolate problem file
                for single in chunk:
                    ensure_writable(single)
                    single_args = base_args + [str(single.resolve())]
                    s_ok, _ = self._run_argfile(single_args, timeout=15)
                    if s_ok:
                        updated += 1

        return updated

    # ─────────────────────────────────────────────
    # Internal: build write argument list
    # ─────────────────────────────────────────────

    @staticmethod
    def _build_write_args(
        tags: Dict[str, str],
        strip_existing: bool,
    ) -> List[str]:
        """Build the ExifTool argument list for a tag rewrite operation."""
        args = ["-overwrite_original", "-m", "-q"]

        if strip_existing:
            args.extend([
                "-all:all=",
                "-xmp:all=",
                "-quicktime:all=",
                "-keys:all=",
                "-userdata:all=",
                "--icc_profile:all",
            ])

        artist = tags.get("Artist", "").strip()
        if artist:
            args.extend([
                f"-Artist={artist}",
                f"-Creator={artist}",
                f"-Author={artist}",
                f"-By-line={artist}",
                f"-XMP-dc:Creator={artist}",
                f"-QuickTime:Artist={artist}",
                f"-Keys:Artist={artist}",
                f"-UserData:Artist={artist}",
            ])

        copyright_val = tags.get("Copyright", "").strip()
        if copyright_val:
            args.extend([
                f"-Copyright={copyright_val}",
                f"-Rights={copyright_val}",
                f"-XMP-dc:Rights={copyright_val}",
                f"-QuickTime:Copyright={copyright_val}",
                f"-Keys:Copyright={copyright_val}",
                f"-UserData:Copyright={copyright_val}",
            ])

        comment = tags.get("UserComment", "").strip()
        if comment:
            args.extend([
                f"-UserComment={comment}",
                f"-Description={comment}",
                f"-Comment={comment}",
                f"-XMP-dc:Description={comment}",
                f"-QuickTime:Comment={comment}",
                f"-Keys:Description={comment}",
                f"-UserData:Description={comment}",
            ])

        return args

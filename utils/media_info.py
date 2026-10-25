"""
utils/media_info.py
Extract image/video dimensions, orientation (H/V), and duration.
"""
from __future__ import annotations

import subprocess
import json
import os
import shutil
from pathlib import Path
from typing import Optional, NamedTuple

import warnings
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

from utils.file_utils import classify_extension
from utils.safe_log import log_swallowed


__all__ = [
    "MediaDimensions",
    "get_image_dimensions",
    "get_video_dimensions",
    "get_media_dimensions",
    "get_image_info",
    "get_video_info",
    "resolve_ffmpeg_exe",
    "resolve_ffprobe_exe",
]


_RESOLVED_FFMPEG: Optional[str] = None
_RESOLVED_FFPROBE: Optional[str] = None


def _resolve_media_binary(binary_name: str, custom_exe: Optional[str] = None) -> str:
    """Find a functional media binary (ffmpeg or ffprobe) from custom path, system PATH, WinGet, or standard paths."""
    exe_name = f"{binary_name}.exe" if not binary_name.lower().endswith(".exe") else binary_name
    stem = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name

    # 1. Custom / explicitly provided path
    if custom_exe and custom_exe not in (stem, exe_name, ""):
        p = Path(custom_exe)
        if p.is_file():
            return str(p.resolve())
        w = shutil.which(custom_exe)
        if w and os.path.isfile(w):
            return str(Path(w).resolve())

    # 2. System PATH
    w = shutil.which(stem) or shutil.which(exe_name)
    if w and os.path.isfile(w):
        return str(Path(w).resolve())

    # 3. WinGet Packages directory
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_dir.is_dir():
            try:
                for pkg in winget_dir.iterdir():
                    if not pkg.is_dir() or "ffmpeg" not in pkg.name.lower():
                        continue
                    # Fast direct check: */bin/<exe_name> (e.g. ffmpeg-9.0.2-full_build/bin/ffmpeg.exe)
                    matches = list(pkg.glob(f"*/bin/{exe_name}"))
                    if matches and matches[0].is_file():
                        return str(matches[0].resolve())
                    # Direct check: bin/<exe_name>
                    direct_bin = pkg / "bin" / exe_name
                    if direct_bin.is_file():
                        return str(direct_bin.resolve())
                    # Recursive fallback: **/<exe_name>
                    all_matches = list(pkg.glob(f"**/{exe_name}"))
                    if all_matches and all_matches[0].is_file():
                        return str(all_matches[0].resolve())
            except Exception as _bare_exc:
                log_swallowed("MEDIA_INFO", _bare_exc)

        # WinGet Links directory
        link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / exe_name
        if link.is_file():
            return str(link.resolve())

    # 4. Application root & project directories
    try:
        from utils.file_utils import get_app_dir
        app_dir = get_app_dir()
    except Exception:
        app_dir = Path(__file__).resolve().parent.parent

    candidates = [
        app_dir / exe_name,
        app_dir / "bin" / exe_name,
        app_dir / "utils" / exe_name,
        Path(r"C:\Tools\ffmpeg\bin") / exe_name,
        Path(r"C:\ffmpeg\bin") / exe_name,
        Path(r"C:\Program Files\ffmpeg\bin") / exe_name,
        Path(local_app_data) / "Programs" / "ffmpeg" / "bin" / exe_name if local_app_data else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return str(c.resolve())

    # 5. Fallback bare command name
    return stem


def resolve_ffmpeg_exe(custom_exe: str = "ffmpeg") -> str:
    """Find a functional ffmpeg binary from custom path, system PATH, WinGet, or project directory."""
    global _RESOLVED_FFMPEG
    if (
        _RESOLVED_FFMPEG
        and os.path.isfile(_RESOLVED_FFMPEG)
        and (custom_exe in ("ffmpeg", "ffmpeg.exe", "", None) or custom_exe == _RESOLVED_FFMPEG)
    ):
        return _RESOLVED_FFMPEG
    res = _resolve_media_binary("ffmpeg", custom_exe)
    if os.path.isfile(res):
        _RESOLVED_FFMPEG = res
    return res


def resolve_ffprobe_exe(custom_exe: str = "ffprobe") -> str:
    """Find a functional ffprobe binary from custom path, system PATH, WinGet, or project directory."""
    global _RESOLVED_FFPROBE
    if (
        _RESOLVED_FFPROBE
        and os.path.isfile(_RESOLVED_FFPROBE)
        and (custom_exe in ("ffprobe", "ffprobe.exe", "", None) or custom_exe == _RESOLVED_FFPROBE)
    ):
        return _RESOLVED_FFPROBE
    res = _resolve_media_binary("ffprobe", custom_exe)
    if os.path.isfile(res):
        _RESOLVED_FFPROBE = res
    return res



class MediaDimensions(NamedTuple):
    width: int
    height: int
    orientation: str          # 'H' (horizontal) or 'V' (vertical)
    duration_secs: float      # 0.0 for images
    media_type: str           # 'image' | 'video'

    @property
    def size_str(self) -> str:
        """Return '19201080' style string (width then height)."""
        return f"{self.width}{self.height}"


def get_image_dimensions(path: Path) -> Optional[MediaDimensions]:
    """Use Pillow or rawpy to read image size and orientation. Fast, no GPU needed."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            # Handle EXIF rotation (Pillow does NOT auto-rotate on open)
            try:
                from PIL import ExifTags
                exif = img._getexif()  # type: ignore[attr-defined]
                if exif:
                    orient_tag = next(
                        (k for k, v in ExifTags.TAGS.items() if v == "Orientation"),
                        None,
                    )
                    if orient_tag and orient_tag in exif:
                        orient_val = exif[orient_tag]
                        # 5,6,7,8 mean image is rotated 90/270 deg
                        if orient_val in (5, 6, 7, 8):
                            w, h = h, w
            except Exception as _bare_exc:
                log_swallowed("MEDIA_INFO", _bare_exc)
            orientation = "H" if w >= h else "V"
            return MediaDimensions(w, h, orientation, 0.0, "image")
    except Exception:
        # Fallback for RAW camera formats (CR2, NEF, ARW, DNG, etc.)
        try:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                w, h = raw.sizes.width, raw.sizes.height
                if raw.sizes.flip in (5, 6, 7, 8):
                    w, h = h, w
                orientation = "H" if w >= h else "V"
                return MediaDimensions(w, h, orientation, 0.0, "image")
        except Exception:
            return None


def get_video_dimensions(path: Path, ffprobe_exe: Optional[str] = None) -> Optional[MediaDimensions]:
    """Use ffprobe to read video stream dimensions and duration."""
    bin_path = resolve_ffprobe_exe(ffprobe_exe) if ffprobe_exe else resolve_ffprobe_exe()
    try:
        result = subprocess.run(
            [
                bin_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        # Find first video stream
        video_stream = next(
            (s for s in streams if s.get("codec_type") == "video"), None
        )
        if not video_stream:
            return None

        w = int(video_stream.get("width", 0))
        h = int(video_stream.get("height", 0))
        if w == 0 or h == 0:
            return None

        # Handle display matrix rotation (portrait videos shot on phone)
        rotation = 0
        tags = video_stream.get("tags", {})
        if "rotate" in tags:
            rotation = abs(int(tags["rotate"]))
        side_data = video_stream.get("side_data_list", [])
        for sd in side_data:
            if sd.get("side_data_type") == "Display Matrix":
                rotation = abs(int(sd.get("rotation", 0)))
                break
        if rotation in (90, 270):
            w, h = h, w

        duration = float(fmt.get("duration", 0.0))
        orientation = "H" if w >= h else "V"
        return MediaDimensions(w, h, orientation, duration, "video")

    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return None


def get_media_dimensions(path: Path) -> Optional[MediaDimensions]:
    """Auto-detect file type and return dimensions."""
    media_type = classify_extension(path.suffix)
    if media_type in ("image", "raw"):
        return get_image_dimensions(path)
    if media_type == "video":
        return get_video_dimensions(path)
    return None


# Convenient aliases
get_image_info = get_image_dimensions
get_video_info = get_video_dimensions


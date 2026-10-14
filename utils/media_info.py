"""
utils/media_info.py
Extract image/video dimensions, orientation (H/V), and duration.
"""
from __future__ import annotations

import subprocess
import json
from pathlib import Path
from typing import Optional, NamedTuple

import warnings
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

from utils.file_utils import classify_extension


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
                try:
                    from core.app_logcat import logcat
                    logcat.w("MEDIA_INFO", f"Loi im lang [utils/media_info.py:53]: {_bare_exc}")
                except Exception:
                    pass
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


def get_video_dimensions(path: Path, ffprobe_exe: str = "ffprobe") -> Optional[MediaDimensions]:
    """Use ffprobe to read video stream dimensions and duration."""
    try:
        result = subprocess.run(
            [
                ffprobe_exe,
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


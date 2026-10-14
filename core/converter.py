"""
core/converter.py
Image and video format converter.
Output is always a COPY at user-specified path (original never overwritten).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image
from utils.safe_log import log_swallowed
Image.MAX_IMAGE_PIXELS = None


IMAGE_FORMAT_MAP = {
    ".jpg":  "JPEG",
    ".jpeg": "JPEG",
    ".png":  "PNG",
    ".webp": "WEBP",
    ".bmp":  "BMP",
    ".tiff": "TIFF",
    ".tif":  "TIFF",
    ".gif":  "GIF",
}

SUPPORTED_IMAGE_EXTS = set(IMAGE_FORMAT_MAP.keys())

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".flv", ".m4v"}


class ImageConverter:
    """Convert images between formats using Pillow. Always produces a copy."""

    def convert(
        self,
        src: Path,
        dst: Path,
        quality: int = 90,
        preserve_metadata: bool = True,
    ) -> tuple[bool, str]:
        """
        Convert `src` image to `dst` (different format inferred from extension).
        Returns (success, error_message).
        """
        dst_ext = dst.suffix.lower()
        if dst_ext not in IMAGE_FORMAT_MAP:
            return False, f"Unsupported output format: {dst_ext}"

        pil_format = IMAGE_FORMAT_MAP[dst_ext]

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            img = None
            try:
                img = Image.open(src)
            except Exception:
                # RAW camera formats fallback (rawpy)
                try:
                    import rawpy
                    with rawpy.imread(str(src)) as raw:
                        rgb = raw.postprocess(use_camera_wb=True)
                        img = Image.fromarray(rgb)
                except Exception:
                    img = None

            if img is None:
                return False, f"Cannot open image: {src.name}"

            with img:
                # Convert mode for formats that don't support alpha or CMYK
                if pil_format in ("JPEG",):
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        # Clean white canvas instead of ugly pitch-black background
                        rgba = img.convert("RGBA")
                        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                        canvas.paste(rgba, mask=rgba.split()[3])
                        img = canvas
                    elif img.mode in ("CMYK", "I", "P"):
                        img = img.convert("RGB")

                save_kwargs: dict = {}
                if pil_format == "JPEG":
                    save_kwargs["quality"] = quality
                    save_kwargs["optimize"] = True
                elif pil_format == "WEBP":
                    save_kwargs["quality"] = quality
                    save_kwargs["method"] = 4
                elif pil_format == "PNG":
                    save_kwargs["optimize"] = True

                # Preserve EXIF if possible
                if preserve_metadata:
                    try:
                        exif_data = img.info.get("exif")
                        if exif_data and pil_format in ("JPEG", "WEBP", "PNG"):
                            save_kwargs["exif"] = exif_data
                    except Exception as _bare_exc:
                        log_swallowed("CONVERTER", _bare_exc, label="Bỏ qua lỗi")

                img.save(dst, format=pil_format, **save_kwargs)
            return True, ""

        except Exception as exc:
            return False, str(exc)

    def batch_convert(
        self,
        conversions: list[tuple[Path, Path]],  # [(src, dst), ...]
        quality: int = 90,
        on_progress: Optional[callable] = None,
    ) -> list[dict]:
        """Batch convert. Returns list of {src, dst, success, error}."""
        results = []
        total = len(conversions)
        for i, (src, dst) in enumerate(conversions):
            ok, err = self.convert(src, dst, quality=quality)
            results.append({"src": src, "dst": dst, "success": ok, "error": err})
            if on_progress:
                on_progress(i + 1, total, src)
        return results


class VideoConverter:
    """Convert videos using ffmpeg-python. Always produces a copy."""

    CODEC_MAP = {
        ".mp4":  {"vcodec": "libx264",  "acodec": "aac"},
        ".webm": {"vcodec": "libvpx-vp9", "acodec": "libopus"},
        ".avi":  {"vcodec": "mpeg4",     "acodec": "mp3"},
        ".mkv":  {"vcodec": "libx264",   "acodec": "aac"},
        ".mov":  {"vcodec": "libx264",   "acodec": "aac"},
        ".gif":  {"vcodec": "gif",       "acodec": None},
    }

    @staticmethod
    def _find_ffmpeg_cmd() -> str:
        """Find working ffmpeg executable from local project or system PATH."""
        candidates = [
            Path(__file__).parent.parent / "ffmpeg.exe",
            Path(__file__).parent.parent / "utils" / "ffmpeg.exe",
            Path(r"C:\Tools\ffmpeg\bin\ffmpeg.exe"),
        ]
        for c in candidates:
            if c.is_file():
                return str(c.resolve())
        return "ffmpeg"

    def convert(
        self,
        src: Path,
        dst: Path,
        crf: int = 23,        # Quality (lower = better, 18-28 typical)
        scale: Optional[str] = None,  # e.g. "1280:720" or "iw/2:ih/2"
    ) -> tuple[bool, str]:
        """
        Convert video `src` → `dst`.
        Returns (success, error_message).
        """
        try:
            import ffmpeg
        except ImportError:
            return False, "ffmpeg-python not installed. Run: pip install ffmpeg-python"

        dst_ext = dst.suffix.lower()
        codec_cfg = self.CODEC_MAP.get(dst_ext, {"vcodec": "libx264", "acodec": "aac"})
        cmd_path = self._find_ffmpeg_cmd()

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            stream = ffmpeg.input(str(src))

            kwargs = {"crf": crf, "loglevel": "error"}
            if codec_cfg["vcodec"]:
                kwargs["vcodec"] = codec_cfg["vcodec"]
            if codec_cfg.get("acodec") and dst_ext != ".gif":
                kwargs["acodec"] = codec_cfg["acodec"]

            if scale:
                stream = ffmpeg.filter(stream, "scale", scale)

            stream = ffmpeg.output(stream, str(dst), **kwargs)
            ffmpeg.run(stream, cmd=cmd_path, overwrite_output=True, quiet=True)
            return True, ""

        except Exception as exc:
            return False, str(exc)

"""
utils/media_extractor.py
Multi-format media tensor extractor for GPU pHash computation.
Supports standard images, RAW camera files (rawpy) and video frames (opencv).
"""
from __future__ import annotations

import datetime
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

import numpy as np

try:
    import warnings
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import rawpy
    HAS_RAWPY = True
except ImportError:
    HAS_RAWPY = False

try:
    import cv2
    # Suppress C-level FFmpeg/OpenCV log spam
    try:
        cv2.setLogLevel(0)
    except Exception:
        pass
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import torch
    HAS_TORCH = True
except (ImportError, OSError, Exception):
    HAS_TORCH = False

from utils.file_utils import IMAGE_EXTS, RAW_EXTS, VIDEO_EXTS


# ─────────────────────────────────────────────
# Stderr silencer — suppresses C-level FFmpeg noise
# ─────────────────────────────────────────────

@contextmanager
def _silence_c_stderr() -> Generator[None, None, None]:
    """Redirect FD 2 (stderr) to NUL temporarily to block C/C++ log noise."""
    try:
        sys.stderr.flush()
        null_fd = os.open(os.devnull, os.O_WRONLY)
        orig_fd = os.dup(2)
        os.dup2(null_fd, 2)
        os.close(null_fd)
        try:
            yield
        finally:
            sys.stderr.flush()
            os.dup2(orig_fd, 2)
            os.close(orig_fd)
    except Exception:
        yield


# ─────────────────────────────────────────────
# MediaExtractor
# ─────────────────────────────────────────────

class MediaExtractor:
    """
    Extract 32x32 grayscale tensors from images, RAW camera files, and videos
    for GPU-accelerated perceptual hash (pHash) computation.

    Output tensors: shape [1, 1, 32, 32], dtype float32, range [0, 1].
    """

    DCT_SIZE = 32  # Resize target before DCT

    @classmethod
    def is_supported(cls, ext: str) -> bool:
        """Return True if extension is processable by this extractor."""
        e = ext.lower()
        return e in IMAGE_EXTS or e in RAW_EXTS or e in VIDEO_EXTS

    # ─────────────────────────────────────────
    # Public entry points
    # ─────────────────────────────────────────

    @classmethod
    def extract_tensor(cls, path: Path) -> Any:
        """
        Auto-detect media type from extension and extract tensor.
        Returns torch.Tensor if PyTorch is available, else np.ndarray, or None on error.
        """
        ext = path.suffix.lower()
        if ext in RAW_EXTS:
            return cls.extract_raw_tensor(path)
        elif ext in VIDEO_EXTS:
            return cls.extract_video_tensor(path)
        else:
            return cls.extract_image_tensor(path)

    @classmethod
    def _to_tensor(cls, arr: np.ndarray) -> Any:
        """Convert float32 (32, 32) array to [1, 1, 32, 32] tensor or ndarray."""
        if HAS_TORCH:
            return torch.from_numpy(arr).view(1, 1, cls.DCT_SIZE, cls.DCT_SIZE)
        return arr.reshape((1, 1, cls.DCT_SIZE, cls.DCT_SIZE))

    @classmethod
    def extract_image_tensor(cls, path: Path) -> Any:
        """
        Load a standard image (JPEG, PNG, WebP, BMP, TIFF, GIF, HEIC, AVIF)
        and return a [1, 1, 32, 32] float32 tensor/array.
        Applies EXIF auto-rotation via ImageOps.exif_transpose().
        """
        if not HAS_PIL:
            return None
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return None
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("L").resize(
                    (cls.DCT_SIZE, cls.DCT_SIZE),
                    Image.Resampling.BILINEAR,
                )
                arr = np.array(img, dtype=np.float32) / 255.0
                return cls._to_tensor(arr)
        except Exception:
            return None

    @classmethod
    def extract_raw_tensor(cls, path: Path) -> Any:
        """
        Load a RAW camera file (CR2, CR3, NEF, ARW, DNG, RAF, ORF, RW2...)
        via rawpy. Tries embedded JPEG thumbnail first (fast), then full demosaic.
        Returns a [1, 1, 32, 32] float32 tensor/array.
        """
        if not HAS_RAWPY:
            return None
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return None

            with rawpy.imread(str(path)) as raw:
                # Fast path: use embedded JPEG thumbnail
                try:
                    thumb = raw.extract_thumb()
                    if hasattr(rawpy, "ThumbFormat") and thumb.format == rawpy.ThumbFormat.JPEG:
                        if HAS_CV2:
                            arr = cv2.imdecode(
                                np.frombuffer(thumb.data, np.uint8),
                                cv2.IMREAD_GRAYSCALE,
                            )
                            if arr is not None:
                                resized = cv2.resize(
                                    arr, (cls.DCT_SIZE, cls.DCT_SIZE),
                                    interpolation=cv2.INTER_AREA,
                                )
                                return cls._to_tensor(resized.astype(np.float32) / 255.0)
                except Exception:
                    pass

                # Slow path: full demosaic
                rgb = raw.postprocess(
                    use_camera_wb=False,
                    half_size=True,
                    no_auto_bright=True,
                )
                if HAS_CV2:
                    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                    resized = cv2.resize(
                        gray, (cls.DCT_SIZE, cls.DCT_SIZE),
                        interpolation=cv2.INTER_AREA,
                    )
                elif HAS_PIL:
                    p_img = Image.fromarray(rgb).convert("L").resize(
                        (cls.DCT_SIZE, cls.DCT_SIZE),
                        Image.Resampling.BILINEAR,
                    )
                    resized = np.array(p_img, dtype=np.float32)
                else:
                    return None
                return cls._to_tensor(resized.astype(np.float32) / 255.0)

        except Exception:
            return None

    @classmethod
    def extract_video_tensor(cls, path: Path) -> Any:
        """
        Extract up to 3 sampled grayscale frames from the first 3 seconds of a video.
        Averages the 3 frames into a single [1, 1, 32, 32] float32 tensor/array.
        """
        if not HAS_CV2:
            return None
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return None

            frames: list[np.ndarray] = []
            with _silence_c_stderr():
                cap = cv2.VideoCapture(str(path))
                if not cap.isOpened():
                    return None

                fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                max_frame = min(int(fps * 3.0), max(total_frames - 1, 0))

                sample_indices = [
                    int(max_frame * 0.1),
                    int(max_frame * 0.5),
                    int(max_frame * 0.9),
                ] if max_frame > 2 else [0]

                for idx in sample_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        resized = cv2.resize(
                            gray, (cls.DCT_SIZE, cls.DCT_SIZE),
                            interpolation=cv2.INTER_AREA,
                        )
                        frames.append(resized.astype(np.float32) / 255.0)

                cap.release()

            if not frames:
                return None

            avg = np.mean(frames, axis=0)
            return cls._to_tensor(avg.astype(np.float32))

        except Exception:
            return None

    # ─────────────────────────────────────────
    # Metadata helpers
    # ─────────────────────────────────────────

    @classmethod
    def resolve_dimensions_and_date(
        cls,
        path: Path,
        metadata: Dict[str, Any],
    ) -> Tuple[int, int, str]:
        """
        Resolve (width, height, date_str) from an ExifTool metadata dict.

        - Applies EXIF rotation correction (90/270 deg swaps W/H).
        - Falls back to PIL for image dimensions if metadata is missing.
        - Falls back to file ctime/mtime if no EXIF date found.

        Returns:
            (width: int, height: int, date_str: str)   # date_str = 'YYYYMMDD'
        """
        ext = path.suffix.lower()

        width    = metadata.get("ImageWidth")    or metadata.get("SourceImageWidth")  or 0
        height   = metadata.get("ImageHeight")   or metadata.get("SourceImageHeight") or 0
        rotation = metadata.get("Rotation") or 0

        try:
            width    = int(width)
            height   = int(height)
            rotation = int(rotation)
        except (ValueError, TypeError):
            width, height, rotation = 0, 0, 0

        # Swap W/H for portrait-rotated media
        if rotation in (90, 270):
            width, height = height, width

        # PIL fallback for images when ExifTool gives nothing
        if (width == 0 or height == 0) and ext in IMAGE_EXTS and HAS_PIL:
            try:
                with Image.open(path) as img:
                    img = ImageOps.exif_transpose(img)
                    width, height = img.size
            except Exception:
                pass

        # Date resolution — prefer EXIF, fall back to filesystem timestamps
        raw_date = (
            metadata.get("DateTimeOriginal")
            or metadata.get("CreateDate")
            or metadata.get("MediaCreateDate")
        )
        date_str = ""

        if raw_date and isinstance(raw_date, str) and len(raw_date) >= 10:
            # ExifTool returns "YYYY:MM:DD HH:MM:SS" or "YYYY-MM-DD"
            date_str = (
                raw_date[:10]
                .replace(":", "")
                .replace("-", "")
                .replace(" ", "")
            )

        if not date_str or not date_str.isdigit() or len(date_str) != 8:
            try:
                st = path.stat()
                ts = min(st.st_ctime, st.st_mtime)
                date_str = datetime.datetime.fromtimestamp(ts).strftime("%Y%m%d")
            except Exception:
                date_str = datetime.datetime.now().strftime("%Y%m%d")

        return int(width), int(height), date_str

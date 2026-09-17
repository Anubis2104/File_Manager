"""
duplicate/dup_manager.py
Orchestrate pHash and DINOv2 engines. Produce DupGroup objects for the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from utils.file_utils import classify_extension, IMAGE_EXTS, RAW_EXTS


@dataclass
class DupFileItem:
    """Represents a single file inside a duplicate group."""
    path: Path
    similarity: float          # 0.0–1.0
    engine: str                # 'pHash' | 'DINOv2'
    action: str = "none"       # 'keep' | 'delete' | 'move' | 'none'
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    created: Optional[str] = None


@dataclass
class DupGroup:
    """A group of similar/duplicate files."""
    group_id: int
    files: list[DupFileItem] = field(default_factory=list)
    collapsed: bool = False


ProgressCallback = Callable[[int, int, str], None]   # (current, total, status_msg)


class DupManager:
    """
    Two-stage duplicate detection:
      Stage 1 — pHash (fast, detects near-identical images)
      Stage 2 — DINOv2 embedding + FAISS (detects similar content)
    """

    def __init__(
        self,
        phash_threshold: int = 10,
        embedding_threshold: float = 0.95,
        model_name: str = "dinov2_vits14",
        batch_size: int = 32,
    ):
        self.phash_threshold = phash_threshold
        self.embedding_threshold = embedding_threshold
        self.model_name = model_name
        self.batch_size = batch_size

        self._phash_engine = None
        self._embed_engine = None

    # ─────────────────────────────────────────────
    # Public entry points
    # ─────────────────────────────────────────────

    def find_duplicates_phash(
        self,
        image_paths: list[Path],
        on_progress: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> list[DupGroup]:
        """Run pHash engine only. Returns DupGroup list."""
        if not self._phash_engine:
            from duplicate.phash_engine import PHashEngine
            self._phash_engine = PHashEngine()

        if on_progress:
            on_progress(0, len(image_paths), "Bắt đầu tính pHash...")

        hashes = self._phash_engine.compute_batch(
            image_paths,
            batch_size=self.batch_size,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )
        if cancel_check and cancel_check():
            return []

        raw_groups = self._phash_engine.find_duplicate_groups(
            hashes,
            threshold=self.phash_threshold,
            cancel_check=cancel_check,
        )
        if cancel_check and cancel_check():
            return []

        if on_progress:
            on_progress(len(image_paths), len(image_paths), "pHash hoàn thành")

        return self._build_dup_groups(raw_groups, engine="pHash", hashes=hashes)

    def find_duplicates_embedding(
        self,
        image_paths: list[Path],
        on_progress: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> list[DupGroup]:
        """Run DINOv2 + FAISS engine. Returns DupGroup list."""
        if not self._embed_engine:
            from duplicate.embedding_engine import EmbeddingEngine
            self._embed_engine = EmbeddingEngine(
                model_name=self.model_name,
                batch_size=self.batch_size,
            )

        def _prog(cur, tot):
            if on_progress:
                on_progress(cur, tot, f"Trích xuất embeddings... {cur}/{tot}")

        self._embed_engine.build_index(image_paths, on_progress=_prog, cancel_check=cancel_check)
        if cancel_check and cancel_check():
            return []
        raw_groups_with_scores = self._embed_engine.find_all_duplicates(self.embedding_threshold)

        return self._build_dup_groups_with_scores(raw_groups_with_scores, engine="DINOv2")

    def find_duplicates_both(
        self,
        image_paths: list[Path],
        on_progress: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> list[DupGroup]:
        """
        Two-stage: pHash first (fast), then DINOv2 on remaining files.
        Merges results, deduplicates groups.
        """
        # Stage 1: pHash
        if on_progress:
            on_progress(0, len(image_paths), "Giai đoạn 1: pHash...")
        phash_groups = self.find_duplicates_phash(image_paths, on_progress=on_progress, cancel_check=cancel_check)
        if cancel_check and cancel_check():
            return []

        # Files already in pHash groups
        already_grouped = {
            f.path for g in phash_groups for f in g.files
        }
        remaining = [p for p in image_paths if p not in already_grouped]

        dino_groups: list[DupGroup] = []
        if remaining:
            if on_progress:
                on_progress(0, len(remaining), "Giai đoạn 2: DINOv2 + FAISS...")
            dino_groups = self.find_duplicates_embedding(remaining, on_progress=on_progress, cancel_check=cancel_check)

        # Merge and re-number
        all_groups = phash_groups + dino_groups
        for i, g in enumerate(all_groups, start=1):
            g.group_id = i

        return all_groups

    # ─────────────────────────────────────────────
    # Helpers: build DupGroup objects
    # ─────────────────────────────────────────────

    def _build_dup_groups(
        self,
        raw_groups: list[list[Path]],
        engine: str,
        hashes: dict = None,
    ) -> list[DupGroup]:
        groups = []
        for gid, path_list in enumerate(raw_groups, start=1):
            files = []
            for p in path_list:
                stat = _safe_stat(p)
                files.append(DupFileItem(
                    path=p,
                    similarity=1.0,   # pHash: similarity not as scalar
                    engine=engine,
                    width=stat.get("width", 0),
                    height=stat.get("height", 0),
                    size_bytes=stat.get("size", 0),
                ))
            grp = DupGroup(group_id=gid, files=files)
            select_best_keeper(grp)
            groups.append(grp)
        return groups

    def _build_dup_groups_with_scores(
        self,
        raw_groups: list[list[tuple[Path, float]]],
        engine: str,
    ) -> list[DupGroup]:
        groups = []
        for gid, group in enumerate(raw_groups, start=1):
            files = []
            for path, score in group:
                stat = _safe_stat(path)
                files.append(DupFileItem(
                    path=path,
                    similarity=score,
                    engine=engine,
                    width=stat.get("width", 0),
                    height=stat.get("height", 0),
                    size_bytes=stat.get("size", 0),
                ))
            grp = DupGroup(group_id=gid, files=files)
            select_best_keeper(grp)
            groups.append(grp)
        return groups


def select_best_keeper(group: DupGroup) -> None:
    """
    Thuật toán Smart Auto-Keeper:
    Tự động chấm điểm và đánh dấu tệp chất lượng tốt nhất trong nhóm làm 'keep',
    và các bản sao còn lại làm 'delete'.
    Tiêu chí:
      1. Tổng số pixel (Width x Height).
      2. Mức độ bảo toàn định dạng (RAW > PNG > WebP > JPEG).
      3. Kích thước tệp tin (bytes).
    """
    if not group.files:
        return

    def score_file(item: DupFileItem) -> tuple:
        ext = item.path.suffix.lower()
        format_priority = 1
        if ext in ('.cr2', '.nef', '.arw', '.dng'):
            format_priority = 4
        elif ext in ('.png', '.tiff'):
            format_priority = 3
        elif ext == '.webp':
            format_priority = 2

        pixel_count = (item.width or 0) * (item.height or 0)
        return (pixel_count, format_priority, item.size_bytes or 0)

    best_item = max(group.files, key=score_file)
    for f in group.files:
        if f is best_item:
            f.action = "keep"
        else:
            f.action = "delete"



def _safe_stat(path: Path) -> dict:
    """Safely get file size and image dimensions."""
    result = {"size": 0, "width": 0, "height": 0}
    try:
        result["size"] = path.stat().st_size
    except OSError:
        pass
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as img:
            result["width"], result["height"] = img.size
            return result
    except Exception:
        pass
    try:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            result["width"], result["height"] = raw.sizes.width, raw.sizes.height
    except Exception:
        pass
    return result


def collect_image_paths(root: Path, recursive: bool = True) -> list[Path]:
    """Collect all image and RAW camera file paths from a directory."""
    walker = root.rglob("*") if recursive else root.iterdir()
    supported = IMAGE_EXTS | RAW_EXTS
    return [
        p for p in walker
        if p.is_file() and p.suffix.lower() in supported
    ]


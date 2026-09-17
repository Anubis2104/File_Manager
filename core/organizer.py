"""
core/organizer.py
Auto-organize files into date-based or type-based subfolder structures.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from utils.file_utils import RenameOperation, make_unique_path, classify_extension
from utils.date_utils import extract_best_date


class FileOrganizer:
    """
    Plans and executes file organization into structured folders.
    Modes:
      - 'date_year_month':    root / YYYY / MM / file.ext
      - 'date_year_month_day':root / YYYY / MM / DD / file.ext
      - 'media_type':         root / Images / (or Videos/) / file.ext
      - 'extension':          root / JPG / (or MP4/) / file.ext
    """

    def __init__(self, mode: str = "date_year_month", dry_run: bool = True):
        self.mode = mode
        self.dry_run = dry_run

    def plan(self, files: list[Path], target_root: Optional[Path] = None) -> list[RenameOperation]:
        """
        Generate a list of RenameOperation objects moving files into subfolders.
        Uses claimed paths tracking to prevent in-batch collisions.
        """
        ops: list[RenameOperation] = []
        claimed: set[Path] = set()

        from utils.file_utils import is_safe_folder_customization_ini

        for src in files:
            if not src.is_file():
                continue
            if src.name.lower() in ("thumbs.db", ".ds_store"):
                continue
            if is_safe_folder_customization_ini(src):
                continue

            root = target_root or src.parent

            if self.mode == "date_year_month":
                dt, _ = extract_best_date(src)
                if dt:
                    dest_dir = root / f"{dt.year:04d}" / f"{dt.month:02d}"
                else:
                    dest_dir = root / "Unknown_Date"

            elif self.mode == "date_year_month_day":
                dt, _ = extract_best_date(src)
                if dt:
                    dest_dir = root / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
                else:
                    dest_dir = root / "Unknown_Date"

            elif self.mode == "media_type":
                m_type = classify_extension(src.suffix)
                folder_name = {"image": "Images", "raw": "RAW_Images", "video": "Videos"}.get(m_type, "Others")
                dest_dir = root / folder_name

            elif self.mode == "extension":
                ext_folder = (src.suffix.lower().replace(".", "") or "NO_EXT").upper()
                dest_dir = root / ext_folder

            else:
                dest_dir = root

            # Collision-safe destination determination
            candidate = dest_dir / src.name
            if candidate in claimed or candidate.exists():
                candidate = make_unique_path(candidate)
                counter = 1
                stem = candidate.stem
                suffix = candidate.suffix
                while candidate in claimed:
                    candidate = candidate.parent / f"{stem}_{counter:03d}{suffix}"
                    counter += 1

            claimed.add(candidate)
            ops.append(RenameOperation(src=src, dst=candidate, dry_run=self.dry_run))

        return ops

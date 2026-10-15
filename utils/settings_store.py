"""
utils/settings_store.py
Single writer for config/settings.json.

- Atomic: the new content goes to a temp file in the same folder, is flushed to disk,
  then swapped in with os.replace, so a crash mid-write never leaves a truncated file.
- Read-modify-write happens under one lock with a fresh read, so each caller only
  changes its own section and never clobbers keys written by another part of the app.
- os.replace is retried briefly: OneDrive / antivirus can hold the file for a moment.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_lock = threading.RLock()


def default_path() -> Path:
    from utils.file_utils import get_app_dir
    return get_app_dir() / "config" / "settings.json"


def read_settings(path: Optional[Path] = None) -> dict:
    target = Path(path) if path else default_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_write(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update_settings(mutate: Callable[[dict], None], path: Optional[Path] = None) -> dict:
    """Apply `mutate(cfg)` to a fresh read of the file and write it back atomically."""
    target = Path(path) if path else default_path()
    with _lock:
        cfg = read_settings(target)
        mutate(cfg)
        _atomic_write(target, cfg)
        return cfg


def set_section(name: str, value, path: Optional[Path] = None) -> dict:
    return update_settings(lambda cfg: cfg.__setitem__(name, value), path)

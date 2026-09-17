"""
core/background_manager.py
Manages application visual appearance, Windows Acrylic / Blur Behind,
and custom background wallpaper (Images & Looping Live Videos).

Guarantees:
- Selected wallpaper files are safely copied to internal app storage (assets/background/)
  so that background continues to work even if source files are deleted or moved.
- Handles Windows DWM Acrylic / Mica API safely via ctypes.
- Manages appearance settings in config/settings.json.
"""
from __future__ import annotations

import os
import sys
import shutil
import json
import ctypes
from pathlib import Path
from typing import Optional
from utils.file_utils import get_app_dir

APP_ROOT = get_app_dir()
SETTINGS_PATH = APP_ROOT / "config" / "settings.json"
ASSETS_BG_DIR = APP_ROOT / "assets" / "background"

# Supported wallpaper extensions
IMAGE_BG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_BG_EXTS = {".mp4", ".webm", ".avi", ".mov", ".mkv"}


def get_assets_bg_dir() -> Path:
    """Ensure and return the internal background assets directory."""
    ASSETS_BG_DIR.mkdir(parents=True, exist_ok=True)
    return ASSETS_BG_DIR


def load_appearance_settings() -> dict:
    """Load appearance settings from settings.json with sensible defaults."""
    defaults = {
        "background_mode": "default",   # "default" | "blur" | "custom"
        "blur_opacity": 50,             # 0 to 100 (0 = trong suốt hoàn toàn, 100 = mờ đục)
        "blur_enabled": False,          # for backward compatibility
        "background_type": "none",      # "none" | "image" | "video"
        "background_file": "",          # Relative path in assets/ or absolute
        "overlay_opacity": 0.82,        # 0.10 to 0.95 (Dark overlay tint)
    }
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            appr = cfg.get("appearance", {})
            defaults.update(appr)
        except Exception:
            pass

    # Harmonize legacy settings with background_mode
    if "background_mode" not in defaults or defaults["background_mode"] not in ("default", "blur", "custom"):
        if defaults.get("background_type") in ("image", "video") and defaults.get("background_file"):
            defaults["background_mode"] = "custom"
        elif defaults.get("blur_enabled"):
            defaults["background_mode"] = "blur"
        else:
            defaults["background_mode"] = "default"

    return defaults


def save_appearance_settings(appearance_cfg: dict) -> bool:
    """Save appearance configuration into config/settings.json."""
    try:
        cfg = {}
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["appearance"] = appearance_cfg
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def import_background_file(source_path: Path) -> Optional[Path]:
    """
    Safely copy the user-selected background file into internal storage
    (assets/background/) so the wallpaper remains intact even if original
    file is moved or deleted.
    Returns the copied destination Path, or None on failure.
    """
    if not source_path.exists() or not source_path.is_file():
        return None

    bg_dir = get_assets_bg_dir()
    suffix = source_path.suffix.lower()
    dest_filename = f"bg_wallpaper{suffix}"
    dest_path = bg_dir / dest_filename

    try:
        shutil.copy2(source_path, dest_path)
        return dest_path
    except Exception as e:
        print(f"[BackgroundManager] Error copying wallpaper: {e}")
        return None


def resolve_background_file(bg_file_str: str) -> Optional[Path]:
    """Resolve wallpaper path whether stored as relative or absolute."""
    if not bg_file_str:
        return None
    p = Path(bg_file_str)
    if p.is_absolute() and p.exists():
        return p
    # Relative to app root
    candidate = APP_ROOT / bg_file_str
    if candidate.exists():
        return candidate
    # Inside assets/background/
    candidate2 = ASSETS_BG_DIR / p.name
    if candidate2.exists():
        return candidate2
    return None


def apply_acrylic_blur(hwnd: int, enable: bool = True, blur_opacity: int = 50) -> bool:
    """
    Apply Windows 11 / 10 Acrylic / Mica backdrop to the native window handle.
    Fails gracefully if unsupported.
    """
    if sys.platform != "win32":
        return False

    try:
        dwmapi = ctypes.windll.dwmapi
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_mode = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
        )

        win_build = sys.getwindowsversion().build
        if win_build >= 22000:
            backdrop_type = ctypes.c_int(3 if enable else 1)
            res = dwmapi.DwmSetWindowAttribute(
                hwnd, 38, ctypes.byref(backdrop_type), ctypes.sizeof(backdrop_type)
            )
            if enable:
                _apply_win10_acrylic(hwnd, enable, blur_opacity)
            return res == 0
        else:
            return _apply_win10_acrylic(hwnd, enable, blur_opacity)
    except Exception as e:
        print(f"[BackgroundManager] DWM Acrylic error: {e}")
        return False


def _apply_win10_acrylic(hwnd: int, enable: bool, blur_opacity: int = 50) -> bool:
    """Fallback acrylic blur for Windows 10 (17063+)."""
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_uint),
                ("AccentFlags", ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_uint),
            ]

        class WINCOMPATTRDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        accent = ACCENT_POLICY()
        accent.AccentState = 4 if enable else 0  # ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        accent.AccentFlags = 2
        alpha = int((max(0, min(100, blur_opacity)) / 100.0) * 220) if enable else 0
        accent.GradientColor = (alpha << 24) | 0x00101524

        data = WINCOMPATTRDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        user32 = ctypes.windll.user32
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False

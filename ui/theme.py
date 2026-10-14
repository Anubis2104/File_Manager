"""
ui/theme.py
Windows 11 File Explorer theme: semantic color tokens, light/dark following the system,
system accent color, and stylesheet templating.

Stylesheets reference tokens as ``@token_name`` (QSS already uses braces), e.g.
``"color: @text_secondary; border-bottom: 1px solid @stroke_divider;"``.
Use ``style(widget, template)`` instead of ``widget.setStyleSheet`` so the widget is
re-styled when Windows switches between light and dark mode.

Dark values are sampled from Explorer on Windows 11 (docs/reference/explorer_dark_details.png);
light values follow the WinUI 3 / Fluent token set until a light reference is captured.
"""
from __future__ import annotations

import json
import os
import re
import weakref
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory, QWidget

TOKEN_RE = re.compile(r"@([a-z][a-z0-9_]*)")
_QSS_TEMPLATE = Path(__file__).parent / "styles" / "explorer.qss"


@dataclass(frozen=True)
class Tokens:
    name: str               # "dark" | "light"
    # Surfaces
    bg_base: str            # window, content area, navigation pane
    bg_layer: str           # status bar, slightly raised strips
    bg_card: str            # preview area, cards, flyouts
    bg_chrome: str          # title/address rows when Mica is unavailable
    fill_control: str       # text boxes (address, search), buttons at rest
    fill_hover: str         # subtle hover on list items / toolbar buttons
    fill_pressed: str
    fill_selected: str      # selected item (navigation pane, lists)
    # Strokes
    stroke_divider: str     # pane separators, column dividers
    stroke_control: str     # control borders, card outlines
    # Text
    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_disabled: str
    # Accent (overridden with the Windows accent color at runtime)
    accent: str
    text_on_accent: str
    # Status
    success: str
    warning: str
    danger: str
    success_bg: str
    warning_bg: str
    danger_bg: str


DARK = Tokens(
    name="dark",
    bg_base="#191919", bg_layer="#1c1c1c", bg_card="#222222", bg_chrome="#202020",
    fill_control="#2b2b2b", fill_hover="#2d2d2d", fill_pressed="#292929", fill_selected="#333333",
    stroke_divider="#2b2b2b", stroke_control="#383838",
    text_primary="#ffffff", text_secondary="#dedede", text_tertiary="#9a9a9a", text_disabled="#5d5d5d",
    accent="#60cdff", text_on_accent="#000000",
    success="#6ccb5f", warning="#fce100", danger="#ff99a4",
    success_bg="#393d1b", warning_bg="#433519", danger_bg="#442726",
)

LIGHT = Tokens(
    name="light",
    bg_base="#ffffff", bg_layer="#f9f9f9", bg_card="#f3f3f3", bg_chrome="#f3f3f3",
    fill_control="#ffffff", fill_hover="#f5f5f5", fill_pressed="#f0f0f0", fill_selected="#e5e5e5",
    stroke_divider="#e5e5e5", stroke_control="#d1d1d1",
    text_primary="#1a1a1a", text_secondary="#5d5d5d", text_tertiary="#8a8a8a", text_disabled="#a0a0a0",
    accent="#005fb8", text_on_accent="#ffffff",
    success="#0f7b0f", warning="#9d5d00", danger="#c42b1c",
    success_bg="#dff6dd", warning_bg="#fff4ce", danger_bg="#fde7e9",
)

_TOKEN_NAMES = {f.name for f in fields(Tokens)} - {"name"}


def resolve(template: str, tokens: Tokens, assets: Optional[dict] = None) -> str:
    """Replace ``@token`` (colors) and ``@asset`` (generated image paths); unknown names stay."""
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name in _TOKEN_NAMES:
            return getattr(tokens, name)
        if assets and name in assets:
            return assets[name]
        return m.group(0)
    return TOKEN_RE.sub(sub, template)


# Fluent-style 16px chevrons; QSS `image:` needs files, so they are written per scheme.
_ASSET_SVGS = {
    "chevron_right": '<path d="M6 3.5 10.5 8 6 12.5"/>',
    "chevron_down":  '<path d="M3.5 6 8 10.5 12.5 6"/>',
}


def _write_assets(tokens: Tokens) -> dict:
    """Write theme-colored SVG assets to a cache dir; returns {name: posix path}."""
    import tempfile
    out_dir = Path(tempfile.gettempdir()) / "fmpro_theme"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, body in _ASSET_SVGS.items():
        target = out_dir / f"{name}_{tokens.name}_{tokens.text_secondary.lstrip('#')}.svg"
        if not target.exists():
            target.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" '
                f'stroke="{tokens.text_secondary}" stroke-width="1.2" stroke-linecap="round" '
                f'stroke-linejoin="round">{body}</svg>',
                encoding="utf-8",
            )
        paths[name] = target.as_posix()
    return paths


def _accent_variant(base: QColor, dark: bool) -> str:
    """Fluent uses a lighter accent shade on dark backgrounds, a darker one on light."""
    c = base.lighter(150) if dark else base.darker(115)
    return c.name()


def _saved_mode() -> str:
    """'system' | 'light' | 'dark' from env FMPRO_THEME or config appearance.theme."""
    env = os.environ.get("FMPRO_THEME", "").strip().lower()
    if env in ("system", "light", "dark"):
        return env
    try:
        from utils.file_utils import get_app_dir
        cfg = json.loads((get_app_dir() / "config" / "settings.json").read_text(encoding="utf-8"))
        mode = str(cfg.get("appearance", {}).get("theme", "system")).lower()
        return mode if mode in ("system", "light", "dark") else "system"
    except Exception:
        return "system"


class ThemeManager(QObject):
    """Process-wide theme state. Re-styles bound widgets when the scheme changes."""

    changed = pyqtSignal(object)   # Tokens

    _instance: Optional["ThemeManager"] = None

    def __init__(self):
        super().__init__()
        self._app: Optional[QApplication] = None
        self._mode = "system"
        self.tokens: Tokens = DARK
        self._assets: dict = {}
        self._applying = False
        self._bound: "weakref.WeakKeyDictionary[QWidget, str]" = weakref.WeakKeyDictionary()

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    # ── lifecycle ─────────────────────────────────────────────

    def install(self, app: QApplication, mode: Optional[str] = None) -> None:
        self._app = app
        self._mode = mode or _saved_mode()
        if "windows11" in (k.lower() for k in QStyleFactory.keys()):
            app.setStyle("windows11")
        app.styleHints().colorSchemeChanged.connect(lambda *_: self._apply())
        self._apply()

    def set_mode(self, mode: str) -> None:
        if mode not in ("system", "light", "dark"):
            raise ValueError(mode)
        self._mode = mode
        self._apply()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dark(self) -> bool:
        return self.tokens.name == "dark"

    def _system_is_dark(self) -> bool:
        if self._app is not None:
            scheme = self._app.styleHints().colorScheme()
            if scheme != Qt.ColorScheme.Unknown:
                return scheme == Qt.ColorScheme.Dark
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except Exception:
            return True

    def _apply(self) -> None:
        app = self._app
        if app is None or self._applying:
            return
        # setColorScheme()/unsetColorScheme() below can emit colorSchemeChanged synchronously
        self._applying = True
        try:
            self._apply_now(app)
        finally:
            self._applying = False

    def _apply_now(self, app: QApplication) -> None:
        hints = app.styleHints()
        if self._mode == "system":
            hints.unsetColorScheme()
            dark = self._system_is_dark()
        else:
            dark = self._mode == "dark"
            # Makes the native windows11 style draw controls in the forced scheme too
            hints.setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)

        base = DARK if dark else LIGHT
        sys_accent = app.palette().color(QPalette.ColorRole.Accent)
        if sys_accent.isValid() and sys_accent.alpha() > 0:
            base = replace(base, accent=_accent_variant(sys_accent, dark))
        self.tokens = base
        try:
            self._assets = _write_assets(base)
        except OSError:
            self._assets = {}   # arrows fall back to Qt's defaults

        app.setPalette(self._build_palette(base))
        app.setStyleSheet(self.qss(_QSS_TEMPLATE.read_text(encoding="utf-8")) if _QSS_TEMPLATE.exists() else "")
        for widget, template in list(self._bound.items()):
            try:
                widget.setStyleSheet(self.qss(template))
            except RuntimeError:     # C++ object already deleted
                pass
        self.changed.emit(base)

    @staticmethod
    def _build_palette(t: Tokens) -> QPalette:
        p = QPalette()
        C = QColor
        role = QPalette.ColorRole
        for r, value in (
            (role.Window, t.bg_base), (role.WindowText, t.text_primary),
            (role.Base, t.bg_base), (role.AlternateBase, t.bg_layer),
            (role.Text, t.text_primary), (role.PlaceholderText, t.text_tertiary),
            (role.Button, t.fill_control), (role.ButtonText, t.text_primary),
            (role.ToolTipBase, t.bg_card), (role.ToolTipText, t.text_primary),
            (role.Highlight, t.accent), (role.HighlightedText, t.text_on_accent),
            (role.Accent, t.accent), (role.Link, t.accent), (role.BrightText, t.danger),
            (role.Mid, t.stroke_control), (role.Midlight, t.fill_hover),
            (role.Dark, t.stroke_divider), (role.Light, t.fill_control), (role.Shadow, "#000000"),
        ):
            p.setColor(r, C(value))
        dis = QPalette.ColorGroup.Disabled
        for r in (role.WindowText, role.Text, role.ButtonText):
            p.setColor(dis, r, C(t.text_disabled))
        return p

    # ── styling API ───────────────────────────────────────────

    def qss(self, template: str) -> str:
        return resolve(template, self.tokens, self._assets)

    def bind(self, widget: QWidget, template: str) -> None:
        self._bound[widget] = template
        widget.setStyleSheet(self.qss(template))

    def template(self, widget: QWidget) -> str:
        """The unresolved template bound to `widget` (to share a style between widgets)."""
        return self._bound.get(widget, "")

    def color(self, name: str) -> QColor:
        return QColor(getattr(self.tokens, name))


def theme() -> ThemeManager:
    return ThemeManager.instance()


def style(widget: QWidget, template: str) -> None:
    """Theme-aware replacement for ``widget.setStyleSheet(template)``."""
    ThemeManager.instance().bind(widget, template)


def tok(name: str) -> str:
    """Current hex value of a token (for APIs that take color strings, e.g. SVG icons)."""
    return getattr(ThemeManager.instance().tokens, name)


def qcolor(name: str) -> QColor:
    """Current QColor of a token (call at paint time to follow theme changes)."""
    return ThemeManager.instance().color(name)

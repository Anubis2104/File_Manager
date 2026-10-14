"""
tests/test_theme.py
Explorer theme layer (ui/theme.py): token resolution, light/dark switching of bound
widgets, legible contrast, and a guard against hard-coded colors creeping back.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import fields
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from ui import theme as th  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HEX = re.compile(r"^#[0-9a-f]{6}$")
HEX_ALPHA = re.compile(r"^#[0-9a-f]{8}$")   # #AARRGGBB layers over Mica


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def manager(app):
    tm = th.theme()
    if tm._app is None:
        tm.install(app, mode="dark")
    previous = tm.mode
    yield tm
    tm.set_mode(previous)


def _luminance(hex_color: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("tokens", [th.DARK, th.LIGHT], ids=["dark", "light"])
def test_every_token_is_a_hex_color(tokens):
    for f in fields(th.Tokens):
        if f.name != "name":
            pattern = HEX_ALPHA if f.name.endswith("_on_mica") else HEX
            assert pattern.match(getattr(tokens, f.name)), f"{tokens.name}.{f.name}"


@pytest.mark.parametrize("tokens", [th.DARK, th.LIGHT], ids=["dark", "light"])
def test_text_contrast_meets_wcag(tokens):
    for surface in ("bg_base", "bg_layer", "fill_selected", "fill_hover"):
        bg = getattr(tokens, surface)
        assert contrast(tokens.text_primary, bg) >= 7.0, f"text_primary on {surface}"
        assert contrast(tokens.text_secondary, bg) >= 4.5, f"text_secondary on {surface}"
    assert contrast(tokens.text_on_accent, tokens.accent) >= 4.5


def test_resolve_replaces_known_tokens_and_keeps_unknown():
    out = th.resolve("color: @text_primary; border: 1px solid @stroke_divider; x: @not_a_token;", th.DARK)
    assert out == f"color: {th.DARK.text_primary}; border: 1px solid {th.DARK.stroke_divider}; x: @not_a_token;"


def test_global_stylesheet_has_no_unknown_tokens():
    qss = (ROOT / "ui" / "styles" / "explorer.qss").read_text(encoding="utf-8")
    qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)   # comments may mention @token syntax
    leftovers = set(th.TOKEN_RE.findall(th.resolve(qss, th.DARK, th._write_assets(th.DARK))))
    assert not leftovers, f"typo'd tokens in explorer.qss: {leftovers}"


def test_global_stylesheet_leaves_native_controls_alone():
    """Rules on these selectors would stop Qt drawing them with the windows11 style."""
    qss = (ROOT / "ui" / "styles" / "explorer.qss").read_text(encoding="utf-8")
    selectors = re.findall(r"^([^\s/{][^{]*)\{", qss, re.M)
    native = re.compile(r"(?<![\w#])(QPushButton|QScrollBar|QMenu|QCheckBox|QRadioButton|QComboBox|QToolTip|QSpinBox)(?![\w#])")
    offenders = [s.strip() for s in selectors if native.search(s.replace("QPushButton#", "#"))]
    assert not offenders, offenders


def test_bound_widget_follows_mode_switch(manager):
    label = QLabel("x")
    th.style(label, "QLabel { color: @text_primary; background: @bg_base; }")

    manager.set_mode("light")
    assert th.LIGHT.text_primary in label.styleSheet()
    assert th.tok("bg_base") == th.LIGHT.bg_base

    manager.set_mode("dark")
    assert th.DARK.text_primary in label.styleSheet()
    assert th.theme().is_dark


def test_template_is_shareable_between_widgets(manager):
    a, b = QLabel("a"), QLabel("b")
    th.style(a, "color: @accent;")
    th.style(b, th.theme().template(a))
    manager.set_mode("light")
    assert b.styleSheet() == a.styleSheet()


def test_settings_dialog_saves_and_applies_theme(manager, monkeypatch):
    import ui.dialogs.settings_dialog as sd

    saved = {}
    monkeypatch.setattr(sd, "save_settings", lambda cfg: saved.update(cfg) or True)  # never touch real config
    monkeypatch.setattr(sd.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dlg = sd.SettingsDialog()
    dlg.combo_theme.setCurrentIndex(dlg.combo_theme.findData("light"))
    dlg._save()

    assert saved["appearance"]["theme"] == "light"
    assert manager.mode == "light" and not manager.is_dark


def test_no_raw_palette_colors_left_in_ui():
    """Neutral/accent colors of the old navy theme must go through tokens."""
    old_palette = {"#0b0f19", "#111827", "#1e293b", "#334155", "#38bdf8", "#0a84ff", "#1c1c1e",
                   "#2c2c2e", "#3a3a3c", "#8e8e93", "#94a3b8", "#cbd5e1", "#0369a1", "#0284c7"}
    hits = []
    for path in (ROOT / "ui").rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for h in re.findall(r"#[0-9a-fA-F]{6}\b", line):
                if h.lower() in old_palette:
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {h}")
    assert not hits, "\n".join(hits)

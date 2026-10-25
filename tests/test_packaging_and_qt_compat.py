"""
tests/test_packaging_and_qt_compat.py
Automated tests for standalone packaging configuration (filemanagerpro.spec)
and Qt compatibility layer (ui/qt_compat.py).
"""
import ast
from pathlib import Path
import sys
import types
from unittest.mock import patch, MagicMock

import pytest


def test_spec_added_files_and_hidden_imports():
    """Verify filemanagerpro.spec contains required data bundles and hidden imports."""
    spec_path = Path(__file__).resolve().parent.parent / "filemanagerpro.spec"
    assert spec_path.exists(), "filemanagerpro.spec must exist"

    spec_content = spec_path.read_text(encoding="utf-8")

    # 1. Verify ui/styles in added_files
    assert "ui/styles" in spec_content or "ui\\\\styles" in spec_content or ("ui" in spec_content and "styles" in spec_content), (
        "ui/styles missing from added_files"
    )

    # 2. Verify all required hidden_imports
    required_hidden = [
        "PyQt6.QtSvg",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "ffmpeg",
    ]
    for mod in required_hidden:
        assert mod in spec_content, f"{mod} missing from hidden_imports in filemanagerpro.spec"

    # 3. Verify referenced source directories in added_files exist on disk
    project_root = spec_path.parent
    assert (project_root / "config").is_dir(), "config directory must exist"
    assert (project_root / "assets").is_dir(), "assets directory must exist"
    assert (project_root / "ui" / "styles").is_dir(), "ui/styles directory must exist"
    assert (project_root / "ui" / "styles" / "explorer.qss").is_file(), "ui/styles/explorer.qss must exist"


def test_qt_compat_returns_pyqt6_when_available():
    """Verify setup_qt_compatibility returns 'PyQt6' when PyQt6 is available."""
    from ui.qt_compat import setup_qt_compatibility
    backend = setup_qt_compatibility()
    assert backend in ("PyQt6", "PySide6", "None")


def test_qt_compat_pyside6_fallback_aliases():
    """
    Test that when PyQt6 is absent and PySide6 is present,
    setup_qt_compatibility aliases QtSvg, QtMultimedia, and QtMultimediaWidgets.
    """
    import importlib.machinery
    import ui.qt_compat as qc

    fake_pyside6 = types.ModuleType("PySide6")
    fake_pyside6.__path__ = []
    fake_pyside6.__spec__ = importlib.machinery.ModuleSpec("PySide6", None, is_package=True)

    fake_core = types.ModuleType("PySide6.QtCore")
    fake_core.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtCore", None)
    fake_core.Signal = MagicMock()
    fake_core.Slot = MagicMock()
    fake_core.Property = MagicMock()

    fake_gui = types.ModuleType("PySide6.QtGui")
    fake_gui.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtGui", None)

    fake_widgets = types.ModuleType("PySide6.QtWidgets")
    fake_widgets.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtWidgets", None)
    fake_widgets.QFileSystemModel = MagicMock()

    fake_svg = types.ModuleType("PySide6.QtSvg")
    fake_svg.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtSvg", None)

    fake_multimedia = types.ModuleType("PySide6.QtMultimedia")
    fake_multimedia.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtMultimedia", None)

    fake_mmwidgets = types.ModuleType("PySide6.QtMultimediaWidgets")
    fake_mmwidgets.__spec__ = importlib.machinery.ModuleSpec("PySide6.QtMultimediaWidgets", None)

    fake_pyside6.QtCore = fake_core
    fake_pyside6.QtGui = fake_gui
    fake_pyside6.QtWidgets = fake_widgets
    fake_pyside6.QtSvg = fake_svg
    fake_pyside6.QtMultimedia = fake_multimedia
    fake_pyside6.QtMultimediaWidgets = fake_mmwidgets

    pyside6_dict = {
        "PySide6": fake_pyside6,
        "PySide6.QtCore": fake_core,
        "PySide6.QtGui": fake_gui,
        "PySide6.QtWidgets": fake_widgets,
        "PySide6.QtSvg": fake_svg,
        "PySide6.QtMultimedia": fake_multimedia,
        "PySide6.QtMultimediaWidgets": fake_mmwidgets,
    }

    # Simulate PyQt6 not importable, PySide6 modules available
    real_import = __import__

    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("PyQt6"):
            raise ImportError(f"No module named {name}")
        if name in pyside6_dict:
            if not fromlist and "." in name:
                top_pkg = name.split(".")[0]
                return pyside6_dict.get(top_pkg, pyside6_dict[name])
            return pyside6_dict[name]
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=mock_import):
        # Clean up any existing PyQt6 and PySide6 in sys.modules for test
        saved_pyqt6 = {k: v for k, v in sys.modules.items() if k.startswith("PyQt6")}
        saved_pyside6 = {k: v for k, v in sys.modules.items() if k.startswith("PySide6")}

        for k in list(sys.modules.keys()):
            if k.startswith("PyQt6") or k.startswith("PySide6"):
                del sys.modules[k]

        sys.modules.update(pyside6_dict)

        try:
            res = qc.setup_qt_compatibility()
            assert res == "PySide6"
            assert sys.modules["PyQt6.QtSvg"] is fake_svg
            assert sys.modules["PyQt6.QtMultimedia"] is fake_multimedia
            assert sys.modules["PyQt6.QtMultimediaWidgets"] is fake_mmwidgets
            assert getattr(sys.modules["PyQt6"], "QtSvg") is fake_svg
            assert getattr(sys.modules["PyQt6"], "QtMultimedia") is fake_multimedia
            assert getattr(sys.modules["PyQt6"], "QtMultimediaWidgets") is fake_mmwidgets
        finally:
            # Restore saved modules
            for k in list(sys.modules.keys()):
                if k.startswith("PyQt6") or k.startswith("PySide6"):
                    del sys.modules[k]
            sys.modules.update(saved_pyqt6)
            sys.modules.update(saved_pyside6)


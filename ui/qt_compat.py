"""
ui/qt_compat.py
Universal Qt compatibility layer (PySide6 / PyQt6).
Enables seamless execution under Windows 11 Smart App Control & Application Control Policy.
"""
from __future__ import annotations

import sys


def setup_qt_compatibility() -> str:
    """
    Ensure Qt bindings are accessible via PyQt6 aliases.
    Prefers PySide6 on Windows 11 to adhere to Application Control Policy (signed binaries).
    """
    try:
        import PyQt6.QtWidgets  # Test if blocked by App Control
        return "PyQt6"
    except (ImportError, OSError):
        pass

    try:
        import PySide6.QtCore as _core
        import PySide6.QtGui as _gui
        import PySide6.QtWidgets as _widgets

        _core.pyqtSignal = _core.Signal
        _core.pyqtSlot = _core.Slot
        if not hasattr(_core, "pyqtProperty"):
            _core.pyqtProperty = _core.Property

        # Compatibility for QFileSystemModel location in PySide6 vs PyQt6
        if not hasattr(_gui, "QFileSystemModel"):
            _gui.QFileSystemModel = _widgets.QFileSystemModel

        class _PyQt6Namespace:
            QtCore = _core
            QtGui = _gui
            QtWidgets = _widgets

        sys.modules["PyQt6"] = _PyQt6Namespace
        sys.modules["PyQt6.QtCore"] = _core
        sys.modules["PyQt6.QtGui"] = _gui
        sys.modules["PyQt6.QtWidgets"] = _widgets

        try:
            import PySide6.QtSvg as _svg
            _PyQt6Namespace.QtSvg = _svg
            sys.modules["PyQt6.QtSvg"] = _svg
        except ImportError:
            pass

        try:
            import PySide6.QtMultimedia as _multimedia
            _PyQt6Namespace.QtMultimedia = _multimedia
            sys.modules["PyQt6.QtMultimedia"] = _multimedia
        except ImportError:
            pass

        try:
            import PySide6.QtMultimediaWidgets as _mmwidgets
            _PyQt6Namespace.QtMultimediaWidgets = _mmwidgets
            sys.modules["PyQt6.QtMultimediaWidgets"] = _mmwidgets
        except ImportError:
            pass

        return "PySide6"
    except ImportError:
        return "None"


setup_qt_compatibility()

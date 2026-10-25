"""
main.py
Application entry point. Sets up QApplication and launches MainWindow.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# Force UTF-8 encoding on Windows consoles and subprocesses
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

import warnings
from PIL import Image
# Remove pixel limit to allow inspection of huge high-res images without warnings or crashes
Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

import ui.qt_compat  # Universal Qt compatibility layer (PySide6 / PyQt6)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QFont, QImageReader

from ui.main_window import MainWindow


def main():
    # Remove image allocation limit to allow previewing huge/high-resolution photos
    QImageReader.setAllocationLimit(0)

    # Enable High-DPI scaling (Windows 11 / 4K monitors)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


    app = QApplication(sys.argv)
    app.setApplicationName("FileManagerPro")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FMPro")

    # Install Global Diagnostic Logcat Engine
    from core.app_logcat import AppLogcat
    AppLogcat.instance().install(app)


    # Explorer uses Segoe UI Variable at 9pt
    font = QFont("Segoe UI Variable Text", 9)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    # Windows 11 style + light/dark tokens following the system theme
    from ui.theme import theme
    theme().install(app)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()

    print("[OK] FileManagerPro đang hoạt động. Cửa sổ ứng dụng đã hiển thị trên màn hình.")
    print("     (Đóng cửa sổ ứng dụng hoặc nhấn Ctrl+C trong console để thoát)")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

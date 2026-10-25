# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for FileManagerPro.
Configured for high-performance onedir portable distribution.
"""
from pathlib import Path
import sys

block_cipher = None

project_root = Path('.').resolve()

# Include assets and config directories as bundled data
added_files = [
    (str(project_root / 'config'), 'config'),
    (str(project_root / 'assets'), 'assets'),
    (str(project_root / 'ui' / 'styles'), 'ui/styles'),
]

# Ensure necessary GUI, media processing and file operation modules are included
hidden_imports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    'PIL',
    'PIL.Image',
    'rawpy',
    'cv2',
    'imagehash',
    'scipy',
    'numpy',
    'send2trash',
    'mutagen',
    'piexif',
    'loguru',
    'ffmpeg',
]

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pytest', 'PySide6', 'shiboken6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FileManagerPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FileManagerPro',
)

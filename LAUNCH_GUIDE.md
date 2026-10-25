# FileManagerPro — Complete System & Launch Guide

FileManagerPro is a high-performance desktop file and media management application built with Python and PyQt6. It provides comprehensive digital asset management, lossless metadata processing, dual-engine duplicate file detection (pHash + DINOv2 AI embedding with FAISS), and resilient batch file operations.

This guide provides end-to-end instructions for prerequisites, environment provisioning, running the application across interactive and headless modes, configuration tuning, media workflows, standalone compilation, and troubleshooting.

---

## 1. System Prerequisites

Before launching or deploying FileManagerPro, ensure the following prerequisites are installed on the host system:

| Component | Minimum Requirement | Recommended | Purpose |
|---|---|---|---|
| **Operating System** | Windows 10 (64-bit, Build 19041+) | Windows 11 (64-bit) | Native desktop execution |
| **Python** | Python 3.10 | Python 3.13 or 3.14 (64-bit, tested) | Application runtime environment |
| **FFmpeg & FFprobe** | FFmpeg 5.0+ | Gyan.FFmpeg 7.0+ (WinGet) | Video metadata extraction, probe, and stream-copy stripping |
| **ExifTool (Optional)** | ExifTool 12.0+ | Latest ExifTool standalone | Deep RAW EXIF metadata reading and preservation |
| **RAM** | 4 GB | 8 GB+ | Smooth caching during large directory scans |
| **GPU (Optional)** | None (CPU supported) | NVIDIA GPU, driver 560+ (PyTorch CUDA 12.6 build) | Hardware acceleration for pHash and DINOv2 duplicate detection |

### Installing FFmpeg via WinGet (Recommended)
FileManagerPro includes automatic discovery for FFmpeg binaries installed via the Windows Package Manager (WinGet). To install:

```powershell
winget install Gyan.FFmpeg
```

FileManagerPro automatically discovers `ffmpeg.exe` and `ffprobe.exe` inside:
`%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\*\bin\`
even if the directory is not added to the system `PATH`.

---

## 2. Step 1: Environment Setup & Verification

FileManagerPro uses an isolated Python virtual environment (`.venv`) to ensure deterministic package dependencies without polluting the global Python environment.

### 2.1 Automated Provisioning
The simplest way to initialize the environment is to execute `Run_FileManagerPro.bat`. If `.venv` is missing or missing core packages, the launcher creates the virtual environment and installs all dependencies automatically.

On Windows, PyPI only ships the **CPU-only** PyTorch build. When `nvidia-smi` is present and `.venv` holds a CPU-only torch, the launcher replaces it with the CUDA 12.6 build from `https://download.pytorch.org/whl/cu126` (about 2.5 GB, once). If that download fails the app still starts and duplicate detection runs on the CPU.

### 2.2 Manual Setup via Command Line
If you prefer configuring the environment manually:

```powershell
# 1. Navigate to the project root
cd <path-to>\File_Manager

# 2. Create the virtual environment
python -m venv .venv

# 3. Upgrade pip
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# 4. Install dependencies (standard or AI-enabled)
# For complete AI duplicate detection (Torch + Torchvision + FAISS):
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt pytest pytest-qt

# Or for lightweight core installation:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pytest-qt

# 5. (NVIDIA GPU only) swap the CPU-only torch from PyPI for the CUDA build
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu126
```

### 2.3 Verification of Installed Packages (Acceptance Criterion 1)
Run the programmatic verification one-liner to verify that all 17 required core and AI packages import without errors:

```powershell
.\.venv\Scripts\python.exe -c "import PyQt6, PIL, rawpy, cv2, imagehash, scipy, piexif, mutagen, ffmpeg, send2trash, loguru, tqdm, rich, numpy, torch, torchvision, faiss; print('OK')"
```

**Expected output:**
```
OK
```

---

## 3. Step 2: Running via `Run_FileManagerPro.bat`

The root directory contains `Run_FileManagerPro.bat`, an interactive, zero-configuration launcher designed for everyday desktop use.

### Launcher Features
- **Integrity Validation**: Before launching `main.py`, the batch script verifies that core GUI and imaging modules (`PyQt6`, `PIL`) can be cleanly imported from `.venv`.
- **Automatic Self-Healing**: If `.venv` exists but is missing core packages (e.g. from an interrupted install or corrupt environment), it automatically routes to package installation rather than crashing.
- **Flat Control Flow**: Implemented using labels and `goto` statements to prevent `cmd.exe` parenthesized block parsing hazards (`va was unexpected at this time`).
- **Space-Safe Paths**: Fully supports paths containing spaces and non-ASCII characters.
- **Pass-through Arguments**: Any command-line flags or folder paths passed to `Run_FileManagerPro.bat` are forwarded directly to `main.py %*`.

### Launching:
- **From Windows Explorer**: Double-click `Run_FileManagerPro.bat`.
- **From Terminal**:
  ```cmd
  Run_FileManagerPro.bat
  ```
  Or pass an initial folder to open:
  ```cmd
  Run_FileManagerPro.bat "D:\Photos\2026_Vacation"
  ```

---

## 4. Step 3: Running via Command Line

FileManagerPro supports both interactive graphical execution and headless/offscreen automation for server, test, or CI environments.

### 4.1 Interactive GUI Launch
Run directly using the virtual environment interpreter:

```powershell
.\.venv\Scripts\python.exe main.py
```

To specify an initial folder:
```powershell
.\.venv\Scripts\python.exe main.py "$env:USERPROFILE\Pictures"
```

### 4.2 Headless / Offscreen Launch (Acceptance Criterion 3)
For automated testing, smoke tests, or headless environments without a display monitor, set `QT_QPA_PLATFORM=offscreen`:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -c "import sys, os; from PyQt6.QtWidgets import QApplication; from ui.main_window import MainWindow; app = QApplication(sys.argv); win = MainWindow(); win.show(); print('HEADLESS_SUCCESS'); sys.exit(0)"
```

**Expected output:**
```
HEADLESS_SUCCESS
```

### 4.3 Running the Full Automated Test Suite
To execute all regression tests across UI, metadata, batch launcher, settings wiring, duplicate fallback, and packaging:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

All tests should pass. The MKV metadata test is skipped when FFmpeg is not installed.

---

## 5. Step 4: Configuration & Settings Customization (`config/settings.json`)

All runtime options are centralized in `config/settings.json`. The settings dialog (`Ctrl+,` or clicking **Cài đặt** in the Command Bar) provides an interface to edit these values, which are synchronized directly with `MainWindow`.

### Key Configuration Sections

```json
{
  "general": {
    "default_directory": "D:\\Photos"
  },
  "rename": {
    "default_date_format": "DDMMYY",
    "collision_digits": 3,
    "sanitize_spaces": true
  },
  "duplicate": {
    "default_engine": "both",
    "phash_threshold": 10,
    "embedding_threshold": 0.95,
    "dinov2_model": "dinov2_vits14",
    "batch_size": 128
  },
  "performance": {
    "scanner_workers": 8,
    "use_cuda": true
  },
  "tools": {
    "exiftool_path": "exiftool.exe"
  },
  "appearance": {
    "theme": "system",
    "background_mode": "default",
    "blur_opacity": 50,
    "background_type": "image",
    "background_file": "",
    "overlay_opacity": 0.82
  }
}
```

### Parameter Reference
- `duplicate.default_engine`:
  - `"phash"`: Fast perceptual hashing. Best for identical or resized photos.
  - `"dinov2"`: Deep vision transformer embedding. Best for finding semantically similar angles, crops, or color grades.
  - `"both"`: Two-stage hybrid pipeline. Runs pHash first, then analyzes ungrouped files with DINOv2.
- `duplicate.phash_threshold`: Maximum Hamming distance (0–64) for pHash similarity. Values between 6 and 10 are recommended.
- `duplicate.embedding_threshold`: Cosine similarity cutoff (0.70–0.99) for DINOv2 + FAISS clustering. Default: `0.95`.
- `duplicate.dinov2_model`: Model architecture for vision embeddings:
  - `"dinov2_vits14"`: Small (22M parameters) — Fast, low memory footprint.
  - `"dinov2_vitb14"`: Base (86M parameters) — Standard balance between speed and precision.
  - `"dinov2_vitl14"`: Large (300M parameters) — Maximum feature granularity.
- `performance.scanner_workers`: Number of concurrent worker threads for file scanning and metadata parsing. Defaults to `8` (recommended `4`–`16` depending on CPU cores and storage speed).
- `performance.use_cuda`: `true` runs pHash and DINOv2 on the NVIDIA GPU when one is usable; `false` forces CPU. When CUDA is unavailable, the status-bar badge shows `CPU` and its tooltip gives the reason (CPU-only torch build, driver problem, or torch missing).
- `tools.exiftool_path`: Explicit path to `exiftool.exe` if not located on system `PATH`.

---

## 6. Step 5: Media Processing & Duplicate Detection Workflow

### 6.1 Supported Formats
- **Standard Images**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`, `.tif`, `.gif`
- **Camera RAW**: `.cr2`, `.cr3`, `.nef`, `.arw`, `.dng`, `.raf`, `.rw2`, `.pef`, `.orf`
- **Video Containers**: `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.wmv`, `.flv`, `.m4v`
- **Audio Files**: `.mp3`, `.flac`, `.wav`, `.aac`, `.m4a`, `.ogg`

### 6.2 Duplicate Detection Engine
1. In the Command Bar, select **Tìm tệp trùng lặp** or press `Ctrl+Shift+D` to open the Duplicate Manager page.
2. Select target directories. The file collector automatically gathers all images, RAW files, and supported video formats (`VIDEO_EXTS`).
3. Choose the detection engine (`pHash`, `DINOv2`, or `Cả hai`).
4. Click **Bắt đầu quét**.
5. **Resilient Dual-Engine Fallback**: In `"both"` mode, if DINOv2 embedding fails due to lack of PyTorch or network model weights, the scanner automatically logs a warning and returns the pHash duplicate groups without crashing or throwing an unhandled `RuntimeError`.
6. Review groups in the split comparison view, toggle auto-selection rules (keep oldest, keep highest resolution, keep shortest path), and batch-delete redundant files to the Windows Recycle Bin (`send2trash`).

### 6.3 Lossless Metadata Stripping & Preservation
- Under **Kiểm định & bảo mật** or via the toolbar action **Gọt metadata**:
  - JPEGs and PNGs are processed in RAM with lossless chunk stripping.
  - MKV, WebM, and AVI videos are processed via FFmpeg using `-c copy` stream copying, instantly removing metadata tags without re-encoding video or audio frames.
  - Original file timestamps and creation dates are automatically preserved via the "safe date store" architecture.

---

## 7. Step 6: Standalone Packaging with PyInstaller

FileManagerPro can be bundled into a standalone, portable Windows distribution using the provided `filemanagerpro.spec` file.

> **Not yet verified.** No packaged build has been tested. Known gaps: DINOv2 is downloaded through `torch.hub` at runtime (needs internet), some modules locate ExifTool/config/logs via `__file__` (inside `_internal/` when frozen), and UPX compression can corrupt the CUDA DLLs. Use `Run_FileManagerPro.bat` for now.

### 7.1 Bundling Assets
The PyInstaller specification bundles:
- `config/`: Application settings schemas.
- `assets/`: Icons, vector artwork, and branding assets.
- `ui/styles/`: Stylesheets including `explorer.qss`.
- `hidden_imports`: Explicit inclusions for `PyQt6.QtSvg`, `PyQt6.QtMultimedia`, `PyQt6.QtMultimediaWidgets`, and `ffmpeg`.

### 7.2 Building the Executable
From the repository root within `.venv`:

```powershell
.\.venv\Scripts\pyinstaller filemanagerpro.spec --noconfirm
```

The output will be created at:
```
dist\FileManagerPro\
    FileManagerPro.exe
    config\
    assets\
    ui\styles\
    ...
```

### 7.3 Windows 11 Smart App Control Compatibility (`ui/qt_compat.py`)
`ui/qt_compat.py` provides transparent fallback between `PyQt6` and `PySide6`. On Windows 11 systems where Application Control Policies enforce signed Qt binaries, the compatibility layer automatically initializes `PySide6` with full bindings for `QtCore`, `QtGui`, `QtWidgets`, `QtSvg`, `QtMultimedia`, and `QtMultimediaWidgets`.

---

## 8. Troubleshooting Common Launch Issues

### Issue 1: "Khong tim thay Python duoc cai dat tren may tinh"
- **Cause**: Python is not installed or `python.exe` is not present in the system `PATH`.
- **Solution**:
  1. Download Python 3.10 or newer from [python.org](https://www.python.org/downloads/).
  2. Run the installer and check the box: **`[X] Add python.exe to PATH`**.
  3. Re-run `Run_FileManagerPro.bat`.

### Issue 2: Launcher Crashes with "va was unexpected at this time"
- **Cause**: Older versions of `Run_FileManagerPro.bat` contained parenthesized blocks around multi-line `if/else` statements.
- **Solution**: Ensure you are using the updated `Run_FileManagerPro.bat` that utilizes flat `if not exist ... goto` control flow and dynamic `%ERRORLEVEL%` checks.

### Issue 3: Missing FFmpeg or FFprobe Warning
- **Cause**: FFmpeg binaries are not found on `PATH` or in WinGet directories.
- **Solution**:
  - Run `winget install Gyan.FFmpeg` in PowerShell.
  - Alternatively, download FFmpeg from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and place `ffmpeg.exe` and `ffprobe.exe` into a `bin/` folder inside the project root or into `C:\Tools\ffmpeg\bin\`.

### Issue 4: Qt Platform Plugin Error (`could not find or load the Qt platform plugin "windows"`)
- **Cause**: Missing or incompatible Qt dynamic link libraries in an incomplete Python installation.
- **Solution**:
  - Reinstall Qt binaries in the virtual environment:
    ```powershell
    .\.venv\Scripts\python.exe -m pip install --force-reinstall PyQt6 PyQt6-Qt6
    ```
  - For headless/testing runs, prepend `$env:QT_QPA_PLATFORM="offscreen"`.

### Issue 5: DINOv2 Embedding Fails / Torch Model Download
- **Cause**: Lack of internet access on initial run to download model weights, or limited RAM for large models.
- **Solution**:
  - Open **Cài đặt** (`Ctrl+,`) -> **Trùng lặp**, and switch `dinov2_model` to `dinov2_vits14 (Nhẹ, nhanh)`.
  - Alternatively, select `pHash (Nhanh)` as the default engine.
  - Note that in `"both"` mode, FileManagerPro will automatically fall back to pHash if DINOv2 cannot be initialized.

### Issue 6: PyInstaller Distribution Missing Explorer Stylesheet
- **Cause**: `explorer.qss` not found in `ui/styles/` within the packaged bundle.
- **Solution**: Rebuild using `filemanagerpro.spec`, which explicitly includes `(str(project_root / 'ui' / 'styles'), 'ui/styles')` in `added_files`.

### Issue 7: Status Bar Shows `CPU` on a Machine with an NVIDIA GPU
- **Cause**: `.venv` contains the CPU-only PyTorch build (the PyPI default on Windows), or the NVIDIA driver is missing/outdated.
- **Solution**:
  - Hover the `CPU` badge: the tooltip states the reason.
  - Re-run `Run_FileManagerPro.bat`; it installs the CUDA build automatically, or run step 5 of section 2.2 by hand.
  - Check `.\.venv\Scripts\python.exe -c "import torch; print(torch.version.cuda, torch.cuda.is_available())"` prints a CUDA version and `True`.
  - If it prints a version but `False`, update the NVIDIA driver (560 or newer).

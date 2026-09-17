@echo off
title FileManagerPro - Dong Goi Ban Portable (.exe)
cd /d "%~dp0"

echo ======================================================================
echo           FileManagerPro - He Thong Dong Goi Portable (.exe)
echo ======================================================================
echo.

REM 1. Xac dinh trinh thong dich Python
set "PY_EXEC="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXEC=%~dp0.venv\Scripts\python.exe"
    echo [OK] Su dung Python trong moi truong ao (.venv)
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PY_EXEC=python"
        echo [OK] Su dung Python he thong
    ) else (
        echo [LOI] Khong tim thay Python tren may tinh!
        echo Vui long cai dat Python hoac chay Run_FileManagerPro.bat truoc.
        pause
        exit /b 1
    )
)

REM 2. Kiem tra va cai dat PyInstaller neu chua co
echo.
echo [1/5] Kiem tra cong cu dong goi PyInstaller...
"%PY_EXEC%" -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [THONG BAO] Chua co PyInstaller. Dang tu dong cai dat qua pip...
    "%PY_EXEC%" -m pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [LOI] Khong the cai dat PyInstaller! Vui long kiem tra ket noi mang.
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller da san sang.

REM 3. Don dep thu muc build cu
echo.
echo [2/5] Don dep thu muc ban dung cu...
if exist "build" rmdir /s /q "build"
if exist "dist\FileManagerPro" rmdir /s /q "dist\FileManagerPro"
if exist "dist\FileManagerPro_v1.0_Portable.zip" del /f /q "dist\FileManagerPro_v1.0_Portable.zip"

REM 4. Tien hanh Build qua filemanagerpro.spec
echo.
echo [3/5] Dang bien dich ma nguon va dong goi sang Portable Executable...
echo Vui long cho trong 1-3 phut tuy toc do may tinh...
"%PY_EXEC%" -m PyInstaller filemanagerpro.spec --noconfirm --clean
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [LOI] Qua trinh dong goi PyInstaller gap loi!
    pause
    exit /b 1
)

REM 5. Sao chep cac tep cong cu phu tro doc lap
echo.
echo [4/5] Dong bo cac tai nguyen doc lap (ExifTool, Config, Assets)...
if exist "ExifTool.exe" (
    copy /y "ExifTool.exe" "dist\FileManagerPro\" >nul
)
if exist "exiftool_files" (
    xcopy /e /i /y "exiftool_files" "dist\FileManagerPro\exiftool_files" >nul
)
if exist "config" (
    xcopy /e /i /y "config" "dist\FileManagerPro\config" >nul
)
if exist "assets" (
    xcopy /e /i /y "assets" "dist\FileManagerPro\assets" >nul
)
if not exist "dist\FileManagerPro\logs" (
    mkdir "dist\FileManagerPro\logs"
)
type nul > "dist\FileManagerPro\logs\.gitkeep"

REM 6. Tu dong nen thanh file ZIP Portable san sang upload GitHub Releases
echo.
echo [5/5] Dang nen thanh tep FileManagerPro_v1.0_Portable.zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\FileManagerPro\*' -DestinationPath 'dist\FileManagerPro_v1.0_Portable.zip' -Force"

echo.
echo ======================================================================
echo  [HOAN TAT THANH CONG!]
echo ======================================================================
echo  1. Thu muc chay truc tiep: dist\FileManagerPro\
echo     -> Khoi chay bang: dist\FileManagerPro\FileManagerPro.exe
echo.
echo  2. Tep nen Portable: dist\FileManagerPro_v1.0_Portable.zip
echo     -> Tep nay co the upload truc tiep len GitHub Releases de chia se!
echo ======================================================================
echo.
pause

@echo off
title FileManagerPro Launcher
cd /d "%~dp0"

echo ======================================================================
echo                  FileManagerPro - Trinh Quan Ly Tep Pro
echo ======================================================================

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

REM 1. Neu da co .venv san, khoi dong ngay lap tuc
if exist "%VENV_PY%" (
    echo [OK] Moi truong ao (.venv) da san sang. Dang khoi chay ung dung...
    "%VENV_PY%" main.py %*
    goto :CHECK_EXIT
)

REM 2. Neu chua co .venv, bat dau quy trinh Zero-Config Setup
echo [THONG BAO] Chua tim thay moi truong ao (.venv).
echo [THONG BAO] Tien hanh tu dong thiet lap moi truong lan dau chay...
echo.

REM Kiem tra Python tren he thong
set "SYS_PYTHON="
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "SYS_PYTHON=python"
) else (
    py -3 --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "SYS_PYTHON=py -3"
    )
)

if "%SYS_PYTHON%"=="" (
    echo [LOI / ERROR] Khong tim thay Python duoc cai dat tren may tinh cua ban!
    echo.
    echo Vui long lam theo huong dan sau:
    echo  1. Truy cap trang web chinh thuc: https://www.python.org/downloads/
    echo  2. Tai ve va cai dat phien ban Python 3.10 tro len.
    echo  3. [CUC KY QUAN TRONG]: Nho tich chon o "[X] Add python.exe to PATH" khi cai dat.
    echo  4. Sau khi cai xong, mo lai tep Run_FileManagerPro.bat nay.
    echo.
    pause
    exit /b 1
)

echo [BUOC 1/3] Dang tao moi truong ao Python (.venv)...
%SYS_PYTHON% -m venv "%VENV_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo [LOI] Khong the tao moi truong ao. Vui long kiem tra lai quyen truy cap thu muc.
    pause
    exit /b 1
)

echo [BUOC 2/3] Dang nang cap pip...
"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1

echo [BUOC 3/3] Dang tu dong cai dat cac thu vien tu requirements.txt...
echo Vui long cho trong giay lat...
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [LOI] Cai dat goi thu vien that bai! Vui long kiem tra ket noi mang Internet.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo  [THANH CONG] Toan bo moi truong da duoc cai dat hoan tat!
echo  Dang khoi dong FileManagerPro...
echo ======================================================================
echo.
"%VENV_PY%" main.py %*

:CHECK_EXIT
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [CANH BAO] Ung dung da thoat voi ma loi: %ERRORLEVEL%
    pause
)

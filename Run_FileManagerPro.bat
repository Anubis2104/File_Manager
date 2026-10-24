@echo off
title FileManagerPro Launcher
cd /d "%~dp0"

echo ======================================================================
echo                  FileManagerPro - Trinh Quan Ly Tep Pro
echo ======================================================================

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
REM PyPI chi co torch ban CPU tren Windows; ban CUDA lay tu index rieng cua PyTorch.
REM cu126 chay duoc voi driver NVIDIA tu ban 560 tro len.
set "TORCH_CUDA_INDEX=https://download.pytorch.org/whl/cu126"

REM 1. Neu da co .venv san, kiem tra cac thu vien cot loi [PyQt6, PIL]
if not exist "%VENV_PY%" goto :NO_VENV

echo [KIEM TRA] Kiem tra cac thu vien cot loi trong .venv...
"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1
if errorlevel 1 (
    echo [CANH BAO] .venv da ton tai nhung thieu cac thu vien cot loi [PyQt6, PIL].
    echo [THONG BAO] Dang tu dong tien hanh cai dat thu vien...
    goto :INSTALL_DEPS
)

echo [OK] Moi truong ao [.venv] va cac thu vien cot loi da san sang.
goto :LAUNCH

:NO_VENV
REM 2. Neu chua co .venv, bat dau quy trinh Zero-Config Setup
echo [THONG BAO] Chua tim thay moi truong ao [.venv].
echo [THONG BAO] Tien hanh tu dong thiet lap moi truong lan dau chay...
echo.

REM Kiem tra Python tren he thong
set "SYS_PYTHON="
python --version >nul 2>&1
if not errorlevel 1 (
    set "SYS_PYTHON=python"
) else (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
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

echo [BUOC 1/3] Dang tao moi truong ao Python [.venv]...
%SYS_PYTHON% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [LOI] Khong the tao moi truong ao. Vui long kiem tra lai quyen truy cap thu muc.
    pause
    exit /b 1
)

:INSTALL_DEPS
echo [BUOC 2/3] Dang nang cap pip...
"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1

echo [BUOC 3/3] Dang tu dong cai dat cac thu vien...
echo Vui long cho trong giay lat...
if exist "%~dp0requirements-ai.txt" (
    "%VENV_PY%" -m pip install -r "%~dp0requirements-ai.txt"
) else (
    "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
)
if errorlevel 1 (
    echo [CANH BAO] Cai dat requirements-ai.txt khong thanh cong, thu fallback ve requirements.txt...
    "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [LOI] Cai dat goi thu vien that bai! Vui long kiem tra ket noi mang Internet hoac cache.
        pause
        exit /b 1
    )
)

echo.
echo ======================================================================
echo  [THANH CONG] Toan bo moi truong da duoc cai dat hoan tat!
echo ======================================================================
echo.

:LAUNCH
call :ENSURE_CUDA_TORCH
echo [OK] Dang khoi chay FileManagerPro...
"%VENV_PY%" main.py %*

:CHECK_EXIT
if errorlevel 1 (
    echo.
    echo [CANH BAO] Ung dung da thoat voi ma loi: %ERRORLEVEL%
    pause
)
exit /b

REM ----------------------------------------------------------------------
REM Doi torch ban CPU sang ban CUDA khi may co GPU NVIDIA.
REM Khong bao gio chan viec khoi chay: loi o day chi canh bao roi chay bang CPU.
REM ----------------------------------------------------------------------
:ENSURE_CUDA_TORCH
where nvidia-smi >nul 2>&1
if errorlevel 1 exit /b 0
REM Ma thoat 3 = torch da cai nhung la ban CPU. Thieu torch hoac loi khac: bo qua.
"%VENV_PY%" -c "import sys, torch; sys.exit(3 if torch.version.cuda is None else 0)" >nul 2>&1
if not errorlevel 3 exit /b 0
if errorlevel 4 exit /b 0

echo [GPU] Phat hien card NVIDIA nhung PyTorch trong .venv la ban CPU - phan tich trung lap se cham.
echo [GPU] Dang cai PyTorch ban CUDA tu %TORCH_CUDA_INDEX%
echo [GPU] Tai khoang 2.5 GB, chi thuc hien mot lan. Vui long cho...
"%VENV_PY%" -m pip install --force-reinstall --no-deps torch torchvision --index-url %TORCH_CUDA_INDEX%
if errorlevel 1 (
    echo [CANH BAO] Khong cai duoc PyTorch ban CUDA. Ung dung van chay, AI dung CPU.
    exit /b 0
)
"%VENV_PY%" -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
if errorlevel 1 (
    echo [CANH BAO] Da cai PyTorch CUDA nhung GPU chua dung duoc - hay cap nhat driver NVIDIA.
    exit /b 0
)
echo [GPU] PyTorch CUDA da san sang.
exit /b 0

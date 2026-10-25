"""
Automated Test Suite for Run_FileManagerPro.bat Remediation Verification.
Validates:
1. Batch file existence
2. Absence of cmd.exe parenthesized block syntax errors ('unexpected at this time')
3. Dynamic routing to :INSTALL_DEPS when PyQt6/PIL are missing
4. Clean launch of main.py when PyQt6/PIL are present
5. Fallback from requirements-ai.txt to requirements.txt
6. Static compliance against parse-time %ERRORLEVEL% hazards
7. Path with spaces handling
"""
import os
import shutil
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_BAT = WORKSPACE_ROOT / "Run_FileManagerPro.bat"


def test_batch_file_exists():
    """Verify Run_FileManagerPro.bat exists in repository root."""
    assert LAUNCHER_BAT.exists(), f"Launcher batch file not found at {LAUNCHER_BAT}"


def test_no_parenthesized_block_syntax_crash():
    """
    Verify that executing Run_FileManagerPro.bat (with main.py stubbed)
    does NOT crash with 'va was unexpected at this time.' or any syntax error.
    """
    bat_content = LAUNCHER_BAT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        scripts_dir = tmppath / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        fake_py = scripts_dir / "python.exe"
        fake_py.write_text("fake")

        mock_content = bat_content.replace(
            '"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1',
            'cmd.exe /c "exit /b 0"'
        ).replace(
            '"%VENV_PY%" main.py %*',
            'echo LAUNCHED_MAIN_SUCCESS'
        )
        test_bat = tmppath / "Run_Test.bat"
        test_bat.write_text(mock_content, encoding="utf-8")

        res = subprocess.run(["cmd.exe", "/c", str(test_bat)], capture_output=True, text=True)
        assert "unexpected at this time" not in res.stderr
        assert "unexpected at this time" not in res.stdout
        assert "LAUNCHED_MAIN_SUCCESS" in res.stdout
        assert res.returncode == 0


def test_import_failure_routes_to_install_deps():
    """
    Verify that when PyQt6 or PIL cannot be imported,
    Run_FileManagerPro.bat detects the error dynamically and routes to :INSTALL_DEPS.
    """
    bat_content = LAUNCHER_BAT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        scripts_dir = tmppath / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        fake_py = scripts_dir / "python.exe"
        fake_py.write_text("fake")

        mock_content = bat_content.replace(
            '"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1',
            'cmd.exe /c "exit /b 1"'
        ).replace(
            ':INSTALL_DEPS',
            ':INSTALL_DEPS\necho ROUTED_TO_INSTALL_DEPS\nexit /b 0'
        ).replace(
            '"%VENV_PY%" main.py %*',
            'echo WRONGLY_LAUNCHED_MAIN'
        )
        test_bat = tmppath / "Run_Test.bat"
        test_bat.write_text(mock_content, encoding="utf-8")

        res = subprocess.run(["cmd.exe", "/c", str(test_bat)], capture_output=True, text=True)
        assert "ROUTED_TO_INSTALL_DEPS" in res.stdout
        assert "WRONGLY_LAUNCHED_MAIN" not in res.stdout
        assert "[CANH BAO]" in res.stdout


def test_pip_fallback_recovers_when_requirements_ai_fails():
    """
    Verify that when requirements-ai.txt fails, the fallback to requirements.txt
    succeeds without false fatal exit due to parse-time %ERRORLEVEL%.
    """
    bat_content = LAUNCHER_BAT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        scripts_dir = tmppath / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        fake_py = scripts_dir / "python.exe"
        fake_py.write_text("fake")

        # Force script to enter :INSTALL_DEPS and simulate pip failures
        mock_content = bat_content.replace(
            '"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1',
            'cmd.exe /c "exit /b 1"'
        ).replace(
            '"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1',
            'echo PIP_UPGRADED'
        ).replace(
            '"%VENV_PY%" -m pip install -r "%~dp0requirements-ai.txt"',
            'cmd.exe /c "exit /b 1"'
        ).replace(
            '"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"',
            'cmd.exe /c "exit /b 0"'
        ).replace(
            '"%VENV_PY%" main.py %*',
            'echo LAUNCHED_MAIN_AFTER_FALLBACK'
        )
        # Create a dummy requirements-ai.txt so it takes that branch
        (tmppath / "requirements-ai.txt").write_text("dummy")

        test_bat = tmppath / "Run_Test.bat"
        test_bat.write_text(mock_content, encoding="utf-8")

        res = subprocess.run(["cmd.exe", "/c", str(test_bat)], capture_output=True, text=True)
        assert "Cai dat requirements-ai.txt khong thanh cong, thu fallback" in res.stdout
        assert "LAUNCHED_MAIN_AFTER_FALLBACK" in res.stdout
        assert "Cai dat goi thu vien that bai" not in res.stdout


def test_static_analysis_for_parse_time_hazards():
    """
    Verify statically that Run_FileManagerPro.bat does NOT contain
    parenthesized compound blocks wrapping import checks or %ERRORLEVEL% expansion traps.
    """
    content = LAUNCHER_BAT.read_text(encoding="utf-8")
    
    # Check 1: Must use goto :NO_VENV instead of `if exist "%VENV_PY%" (`
    assert 'if not exist "%VENV_PY%" goto :NO_VENV' in content, (
        "Script must use flat control flow 'if not exist \"%VENV_PY%\" goto :NO_VENV'"
    )
    assert 'if exist "%VENV_PY%" (' not in content, (
        "Forbidden compound block 'if exist \"%VENV_PY%\" (' found!"
    )
    
    # Check 2: Must check `if errorlevel 1` for import check
    assert "if errorlevel 1 (" in content or "if errorlevel 1 goto" in content, (
        "Script must use dynamic 'if errorlevel 1' check"
    )

    # Check 3: No round parentheses in echo statements inside compound blocks
    lines = content.splitlines()
    in_block = False
    for line in lines:
        stripped = line.strip()
        if "(" in stripped and not stripped.startswith("REM") and not stripped.startswith("echo"):
            in_block = True
        if in_block and stripped.startswith("echo"):
            assert "(.venv)" not in stripped, f"Found (.venv) in compound block: {line}"
            assert "(PyQt6, PIL)" not in stripped, f"Found (PyQt6, PIL) in compound block: {line}"
        if in_block and stripped == ")":
            in_block = False


def test_batch_handles_spaces_in_path():
    """Verify that Run_FileManagerPro.bat executes properly in directories with spaces."""
    bat_content = LAUNCHER_BAT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="Path With Spaces ") as tmpdir:
        tmppath = Path(tmpdir)
        scripts_dir = tmppath / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        fake_py = scripts_dir / "python.exe"
        fake_py.write_text("fake")

        mock_content = bat_content.replace(
            '"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1',
            'cmd.exe /c "exit /b 0"'
        ).replace(
            '"%VENV_PY%" main.py %*',
            'echo LAUNCHED_WITH_SPACES_SUCCESS'
        )
        test_bat = tmppath / "Run_Test.bat"
        test_bat.write_text(mock_content, encoding="utf-8")

        res = subprocess.run(["cmd.exe", "/c", str(test_bat)], capture_output=True, text=True)
        assert res.returncode == 0
        assert "LAUNCHED_WITH_SPACES_SUCCESS" in res.stdout


# ─── CUDA torch auto-upgrade (:ENSURE_CUDA_TORCH) ───

_CORE_IMPORT_CHECK = '"%VENV_PY%" -c "import PyQt6, PIL" >nul 2>&1'
_NVIDIA_PROBE = 'where nvidia-smi >nul 2>&1'
_TORCH_BUILD_PROBE = (
    '"%VENV_PY%" -c "import sys, torch; sys.exit(3 if torch.version.cuda is None else 0)" >nul 2>&1'
)
_CUDA_INSTALL = (
    '"%VENV_PY%" -m pip install --force-reinstall --no-deps torch torchvision '
    '--index-url %TORCH_CUDA_INDEX%'
)
_CUDA_VERIFY = '"%VENV_PY%" -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1'


def _run_launcher_with(replacements: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a copy of the launcher with commands swapped for stubs; existing .venv path."""
    content = LAUNCHER_BAT.read_text(encoding="utf-8")
    base = {
        _CORE_IMPORT_CHECK: 'cmd.exe /c "exit /b 0"',
        '"%VENV_PY%" main.py %*': 'echo LAUNCHED_MAIN',
    }
    for old, new in {**base, **replacements}.items():
        assert old in content, f"launcher no longer contains: {old}"
        content = content.replace(old, new)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        scripts_dir = tmppath / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "python.exe").write_text("fake")
        test_bat = tmppath / "Run_Test.bat"
        test_bat.write_text(content, encoding="utf-8")
        return subprocess.run(
            ["cmd.exe", "/c", str(test_bat)], capture_output=True, text=True, stdin=subprocess.DEVNULL
        )


def test_cpu_torch_on_nvidia_machine_is_upgraded_then_launches():
    res = _run_launcher_with({
        _NVIDIA_PROBE: 'cmd.exe /c "exit /b 0"',
        _TORCH_BUILD_PROBE: 'cmd.exe /c "exit /b 3"',
        # A real command (unlike a bare echo) resets ERRORLEVEL, as pip does
        _CUDA_INSTALL: 'cmd.exe /c "echo CUDA_TORCH_INSTALLED"',
        _CUDA_VERIFY: 'cmd.exe /c "exit /b 0"',
    })
    assert "CUDA_TORCH_INSTALLED" in res.stdout
    assert "PyTorch CUDA da san sang" in res.stdout
    assert "LAUNCHED_MAIN" in res.stdout
    assert res.returncode == 0


def test_cuda_install_failure_still_launches_on_cpu():
    res = _run_launcher_with({
        _NVIDIA_PROBE: 'cmd.exe /c "exit /b 0"',
        _TORCH_BUILD_PROBE: 'cmd.exe /c "exit /b 3"',
        _CUDA_INSTALL: 'cmd.exe /c "exit /b 1"',
    })
    assert "Khong cai duoc PyTorch ban CUDA" in res.stdout
    assert "LAUNCHED_MAIN" in res.stdout
    assert "Ung dung da thoat voi ma loi" not in res.stdout
    assert res.returncode == 0


@pytest.mark.parametrize("nvidia_rc, torch_rc", [
    (1, 3),   # no NVIDIA GPU
    (0, 0),   # torch already a CUDA build
    (0, 1),   # torch not installed (pHash-only setup)
])
def test_cuda_upgrade_skipped_when_not_needed(nvidia_rc: int, torch_rc: int):
    res = _run_launcher_with({
        _NVIDIA_PROBE: f'cmd.exe /c "exit /b {nvidia_rc}"',
        _TORCH_BUILD_PROBE: f'cmd.exe /c "exit /b {torch_rc}"',
        _CUDA_INSTALL: 'echo WRONGLY_INSTALLED_CUDA',
    })
    assert "WRONGLY_INSTALLED_CUDA" not in res.stdout
    assert "LAUNCHED_MAIN" in res.stdout
    assert res.returncode == 0


def test_batch_files_use_crlf_line_endings():
    """cmd.exe can mis-resolve goto/call labels in LF-only batch files."""
    raw = LAUNCHER_BAT.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")

@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
set "VENV_DIR=.runtime-venv"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo Python was not found.
    echo Please install Python 3.10 or later and enable "Add Python to PATH".
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or later is required.
    pause
    exit /b 1
)

set "RECREATE_VENV="
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -c "import sys; from PIL import Image; import pymupdf, reportlab" >nul 2>nul
    if errorlevel 1 set "RECREATE_VENV=1"
) else (
    set "RECREATE_VENV=1"
)

if defined RECREATE_VENV (
    if exist "%VENV_DIR%" echo Rebuilding incompatible or broken virtual environment...
    if not exist "%VENV_DIR%" echo Creating virtual environment...
    %PYTHON_CMD% -m venv --clear "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" -c "from PIL import Image; import pymupdf, reportlab" >nul 2>nul
if errorlevel 1 (
    echo Dependencies were installed but native image/PDF modules cannot be loaded.
    echo Run this file again to rebuild the virtual environment.
    pause
    exit /b 1
)

set "AUTOCOMPARE_PORT=%~1"
if not defined AUTOCOMPARE_PORT set "AUTOCOMPARE_PORT=8765"

echo Starting AutoCompare at http://127.0.0.1:%AUTOCOMPARE_PORT% ...
"%VENV_DIR%\Scripts\python.exe" -m autocompare_tool --port "%AUTOCOMPARE_PORT%"
if errorlevel 1 (
    echo AutoCompare web server exited with an error.
    pause
    exit /b 1
)

endlocal

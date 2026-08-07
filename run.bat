@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="

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

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo The existing .venv is broken or points to a Python installation that was removed.
        echo Delete the .venv folder, then run this file again to recreate it.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

set "AUTOCOMPARE_PORT=%~1"
if not defined AUTOCOMPARE_PORT set "AUTOCOMPARE_PORT=8765"

echo Starting AutoCompare at http://127.0.0.1:%AUTOCOMPARE_PORT% ...
".venv\Scripts\python.exe" -m autocompare_tool --port "%AUTOCOMPARE_PORT%"
if errorlevel 1 (
    echo AutoCompare web server exited with an error.
    pause
    exit /b 1
)

endlocal

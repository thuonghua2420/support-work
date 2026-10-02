@echo off
setlocal
cd /d "%~dp0"

set "VENV_DIR=.runtime-venv"
set "VENV_PYTHON=%CD%\%VENV_DIR%\Scripts\python.exe"
set "PYTHON_EXE="
set "RECREATE_VENV="

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 and sys.version_info[1] in (10, 11, 12, 13, 14) else 1)" >nul 2>nul
    if errorlevel 1 (
        set "RECREATE_VENV=1"
    ) else (
        "%VENV_PYTHON%" -c "from PIL import Image; import pymupdf, reportlab, pyodbc, oracledb" >nul 2>nul
        if errorlevel 1 set "RECREATE_VENV=1"
    )
) else (
    set "RECREATE_VENV=1"
)

if not defined RECREATE_VENV goto install_dependencies

rem Avoid Python 3.15 until the constrained native dependencies provide compatible wheels.
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYTHON_EXE for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do if exist "%%P" set "PYTHON_EXE=%%P"
    if not defined PYTHON_EXE for /f "delims=" %%P in ('python%%V -c "import sys; print(sys.executable)" 2^>nul') do if exist "%%P" set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE for /f "delims=" %%P in ('python -c "import sys; print(sys.executable if sys.version_info[0] == 3 and sys.version_info[1] in (10, 11, 12, 13, 14) else chr(10))" 2^>nul') do if exist "%%P" set "PYTHON_EXE=%%P"

if not defined PYTHON_EXE (
    echo No compatible Python installation was found.
    echo AutoCompare requires Python 3.10 through 3.14 on Windows.
    echo Python 3.15 cannot install the current pyodbc and oracledb versions from wheels.
    echo Install Python 3.14, then run this file again: https://www.python.org/downloads/
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 and sys.version_info[1] in (10, 11, 12, 13, 14) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Selected Python is not version 3.10 through 3.14: %PYTHON_EXE%
    pause
    exit /b 1
)

if exist "%VENV_DIR%" echo Rebuilding incompatible or broken virtual environment...
if not exist "%VENV_DIR%" echo Creating virtual environment...
"%PYTHON_EXE%" --version
"%PYTHON_EXE%" -m venv --clear "%VENV_DIR%"
if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
)

:install_dependencies
"%VENV_PYTHON%" --version
echo Installing dependencies...
"%VENV_PYTHON%" -m pip install --only-binary=pyodbc,oracledb -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    echo Check your internet connection and the Python version shown above.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "from PIL import Image; import pymupdf, reportlab, pyodbc, oracledb" >nul 2>nul
if errorlevel 1 (
    echo Dependencies were installed but native modules cannot be loaded.
    echo Run this file again to rebuild the virtual environment.
    pause
    exit /b 1
)

set "AUTOCOMPARE_PORT=%~1"
if not defined AUTOCOMPARE_PORT set "AUTOCOMPARE_PORT=8765"

echo Starting AutoCompare at http://127.0.0.1:%AUTOCOMPARE_PORT% ...
"%VENV_PYTHON%" -m autocompare_tool --port "%AUTOCOMPARE_PORT%"
if errorlevel 1 (
    echo AutoCompare web server exited with an error.
    pause
    exit /b 1
)

endlocal

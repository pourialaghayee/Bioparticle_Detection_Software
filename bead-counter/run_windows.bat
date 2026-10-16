@echo off
setlocal
cd /d "%~dp0"
rem Use the existing environment; otherwise Python 3.12, then any newer Python 3.
set "PYTHON="
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
if not defined PYTHON (py -3.12 -c "" >nul 2>&1 && set "PYTHON=py -3.12")
if not defined PYTHON (py -3 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PYTHON=py -3")
if not defined PYTHON (python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PYTHON=python")
if not defined PYTHON (
    echo Python 3.12 or newer was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/windows/
    echo and keep the option "py launcher" selected, then run this file again.
    goto error
)
%PYTHON% setup_environment.py
if errorlevel 1 goto error
.venv\Scripts\python.exe bead_counter.py %*
if errorlevel 1 goto error
exit /b 0
:error
echo Could not start Bead Counter. See the error above.
pause
exit /b 1

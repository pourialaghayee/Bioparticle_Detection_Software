@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe setup_environment.py
) else (
    py -3.12 setup_environment.py
)
if errorlevel 1 goto error
.venv\Scripts\python.exe bead_counter.py %*
if errorlevel 1 goto error
exit /b 0
:error
echo Could not start Bead Counter. See the error above.
pause
exit /b 1

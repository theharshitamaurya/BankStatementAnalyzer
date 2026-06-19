@echo off
set "APP_DIR=D:\Bank Statement Analyzer"
set "PYTHON_EXE=C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
cd /d "%APP_DIR%"
start "Bank Statement Analyzer Server" "%PYTHON_EXE%" "%APP_DIR%\app\server.py"
timeout /t 2 >nul
start "" "http://127.0.0.1:8765/"

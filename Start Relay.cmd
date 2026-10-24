@echo off
setlocal
cd /d "%~dp0"
set "RELAY_DIR=router"
if exist "%~dp0model-router\manager.py" set "RELAY_DIR=model-router"
where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "Relay" pyw.exe "%~dp0%RELAY_DIR%\manager.py" --open
) else (
  python "%~dp0%RELAY_DIR%\manager.py" --open
)
endlocal

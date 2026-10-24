@echo off
setlocal
cd /d "%~dp0"
set "RELAY_DIR=router"
if exist "%~dp0model-router\router.py" set "RELAY_DIR=model-router"
where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "Codex model router" pyw.exe "%~dp0%RELAY_DIR%\router.py"
) else (
  python "%~dp0%RELAY_DIR%\router.py"
)
endlocal

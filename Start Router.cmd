@echo off
setlocal
cd /d "%~dp0"
set "RELAY_DIR=router"
if exist "%~dp0model-router\router.py" (
  set "RELAY_DIR=model-router"
) else (
  set "CODEX_ROUTER_DEV=1"
  set "CODEX_HOME=%~dp0.dev-codex"
  set "CODEX_ROUTER_SETTINGS=%~dp0.dev-codex\router-settings.json"
  set "CODEX_ROUTER_USAGE_DB=%~dp0.dev-codex\router-usage.sqlite"
)
where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "Codex model router" pyw.exe "%~dp0%RELAY_DIR%\router.py"
) else (
  python "%~dp0%RELAY_DIR%\router.py"
)
endlocal

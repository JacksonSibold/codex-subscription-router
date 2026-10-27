@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0Relay.exe" (
  start "" "%~dp0Relay.exe"
  exit /b 0
)
if exist "%~dp0router\manager.py" if exist "%~dp0desktop\dist\Relay\Relay.exe" (
  start "" "%~dp0desktop\dist\Relay\Relay.exe" --dev
  exit /b 0
)
if exist "%~dp0desktop\dist\Relay\Relay.exe" (
  start "" "%~dp0desktop\dist\Relay\Relay.exe"
  exit /b 0
)
if exist "%~dp0model-router\desktop\Relay.exe" (
  start "" "%~dp0model-router\desktop\Relay.exe"
  exit /b 0
)

set "RELAY_DIR=router"
if exist "%~dp0model-router\manager.py" (
  set "RELAY_DIR=model-router"
) else (
  set "CODEX_ROUTER_DEV=1"
  set "CODEX_HOME=%~dp0.dev-codex"
  set "CODEX_ROUTER_SETTINGS=%~dp0.dev-codex\router-settings.json"
  set "CODEX_ROUTER_USAGE_DB=%~dp0.dev-codex\router-usage.sqlite"
)
where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "Relay" pyw.exe "%~dp0%RELAY_DIR%\manager.py" --open
) else (
  python "%~dp0%RELAY_DIR%\manager.py" --open
)
endlocal

@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\diagnose_mineru_network.ps1"
if errorlevel 1 (
  echo.
  echo Diagnostic script returned an error.
  pause
)
endlocal

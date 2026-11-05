@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
    echo Verification failed. See the error above.
) else (
    echo Verification completed successfully.
)
pause
exit /b %RESULT%

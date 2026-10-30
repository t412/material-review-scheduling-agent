@echo off
setlocal
title Live Trace Generator
cd /d "%~dp0.."
powershell.exe -NoLogo -ExecutionPolicy Bypass -File "%~dp0generate_live_examples.ps1"
set "LIVE_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%LIVE_EXIT_CODE%"=="0" (
  echo Live Trace generation completed successfully.
) else (
  echo Live Trace generation failed with exit code %LIVE_EXIT_CODE%.
)
echo You may close this window after reviewing the result.
pause
exit /b %LIVE_EXIT_CODE%

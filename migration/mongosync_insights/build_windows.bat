@echo off
REM Launcher for build_windows.ps1 (avoids ExecutionPolicy issues in cmd)
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
exit /b %ERRORLEVEL%

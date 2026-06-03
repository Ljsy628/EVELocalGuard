@echo off
setlocal

cd /d "%~dp0"

if exist "dist\EVELocalGuardDebug.exe" (
  "dist\EVELocalGuardDebug.exe"
) else if exist "dist\EVELocalGuard.exe" (
  "dist\EVELocalGuard.exe"
) else (
  echo No EXE found. Please run build_windows_exe.bat or build_windows_console_exe.bat first.
)

echo.
echo If it failed, check:
echo %APPDATA%\EVELocalGuard\crash.log
echo.
pause

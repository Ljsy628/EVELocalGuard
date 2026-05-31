@echo off
setlocal

cd /d "%~dp0"

echo [1/4] Creating virtual environment...
py -3 -m venv .venv
if errorlevel 1 goto error

echo [2/4] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo [3/4] Building EXE...
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name EVELocalGuard ^
  eve_local_guard.py
if errorlevel 1 goto error

echo [4/4] Done.
echo.
echo EXE path:
echo %cd%\dist\EVELocalGuard.exe
echo.
pause
exit /b 0

:error
echo.
echo Build failed. Please check the messages above.
pause
exit /b 1

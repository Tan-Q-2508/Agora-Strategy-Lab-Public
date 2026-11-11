@echo off
rem Double-click to start Agora on Windows. See docs\RUNBOOK.md section 1.
setlocal
title Agora: getting ready
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist "data\logs" mkdir "data\logs"
set "LOG=data\logs\launcher.log"
echo ==== %date% %time% ==== >> "%LOG%"
echo.
echo   Agora
echo   =====
echo.

rem 1. Make sure uv (which installs Python and Agora's parts) is available.
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if not errorlevel 1 goto have_uv
echo Setting up Agora for the first time. This takes a few minutes...
powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex" >> "%LOG%" 2>&1
where uv >nul 2>&1
if not errorlevel 1 goto have_uv
set "MSG=Agora couldn't download its setup tool. Check your internet connection and try again."
goto fail

:have_uv
rem 2. Install or update Python and Agora's parts.
echo Getting everything ready. The first time takes a few minutes...
uv sync --frozen --no-dev >> "%LOG%" 2>&1
if not errorlevel 1 goto start
set "MSG=Agora couldn't install its parts. Check your internet connection and try again."
goto fail

:start
rem 3. Hand over to the tray icon (D-124): Agora runs with no window of its own, opens in its
rem    own app window, and this window closes. Without pythonw, run in this window as before.
if not exist ".venv\Scripts\pythonw.exe" goto console
echo Starting Agora. It opens in its own window; look for the Agora icon by the clock.
start "" ".venv\Scripts\pythonw.exe" -m backend.desktop.tray
exit /b 0

:console
uv run --frozen --no-dev python -m backend.launch
if errorlevel 1 goto stopped_with_error
exit /b 0

:stopped_with_error
echo.
pause
exit /b 1

:fail
echo.
echo %MSG%
echo Details are in data\logs\launcher.log
echo %MSG% >> "%LOG%"
echo.
pause
exit /b 1

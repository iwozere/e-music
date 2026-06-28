@echo off
title MySpotify - Standalone Edition

REM ============================================================================
REM  MySpotify - Standalone Edition  (personal, self-hosted YouTube music app)
REM
REM  WHAT THIS DOES
REM    Runs a small music app on THIS PC only (http://127.0.0.1:8000) and opens
REM    it in your web browser. Nothing is published online - your library is
REM    stored on your own disk, under %LOCALAPPDATA%\iwozere\MySpotify.
REM
REM  PREREQUISITES (install once, then just double-click this file)
REM    1) Python 3.11 or newer   https://www.python.org/downloads/
REM         During install, TICK "Add python.exe to PATH".
REM    2) FFmpeg (for playback)  open PowerShell and run:
REM         winget install Gyan.FFmpeg
REM       then close and reopen this window so PATH refreshes.
REM    3) Internet connection    (to stream from YouTube and to install
REM                               dependencies the very first time)
REM
REM  FIRST RUN takes 1-2 minutes (it sets up a local environment and downloads
REM  dependencies). Every run after that starts in a few seconds.
REM
REM  TO QUIT: close this window, or press Ctrl+C.
REM ============================================================================

echo(
echo  ============================================================
echo    MySpotify - Standalone Edition
echo    Personal music app that runs only on this PC.
echo  ============================================================
echo(

cd /d "%~dp0"

REM --- 1. Locate a Python interpreter -----------------------------------------
set "PYLAUNCH="
where py >nul 2>nul && set "PYLAUNCH=py"
if not defined PYLAUNCH (
    where python >nul 2>nul && set "PYLAUNCH=python"
)
if not defined PYLAUNCH (
    echo  [ERROR] Python was not found on this PC.
    echo          Install Python 3.11+ from https://www.python.org/downloads/
    echo          and TICK "Add python.exe to PATH" during setup, then run this again.
    echo(
    pause
    exit /b 1
)

REM --- 2. First run: create the local environment and install dependencies -----
if not exist ".venv\Scripts\python.exe" (
    echo  [setup] First run detected - creating local environment ^(.venv^)...
    %PYLAUNCH% -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Could not create the virtual environment. Is Python installed correctly?
        echo(
        pause
        exit /b 1
    )
    echo  [setup] Installing dependencies - this can take 1-2 minutes...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
    if errorlevel 1 (
        echo  [ERROR] Dependency installation failed. Check your internet connection and retry.
        echo(
        pause
        exit /b 1
    )
    echo  [setup] Setup complete.
    echo(
)

REM --- 3. Warn (do not block) if FFmpeg is missing -----------------------------
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo  [WARN] FFmpeg was not found on PATH.
    echo         Search will work, but audio PLAYBACK will fail until you install it:
    echo             winget install Gyan.FFmpeg
    echo         Then close and reopen this window.
    echo(
)

REM --- 4. Launch ---------------------------------------------------------------
echo  [run] Starting MySpotify... your browser will open automatically.
echo        Leave this window open while you use the app.
echo(
cd backend
"..\.venv\Scripts\python.exe" -m app.desktop

echo(
echo  MySpotify has stopped. You can close this window.
pause

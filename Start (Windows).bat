@echo off
REM Double-click this file to open the Niche Automation Script Hub menu.
REM The first time, it sets up a private "toolbox" (.venv) for the hub.
title Niche Automation Script Hub
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python is not installed yet.
    echo  Opening the download page. Install it, tick "Add python.exe to PATH",
    echo  then double-click this file again.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time. This takes about a minute...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo  Could not set up the toolbox. Please reinstall Python from python.org
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
)

".venv\Scripts\python.exe" start.py
echo.
pause

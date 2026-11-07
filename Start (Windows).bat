@echo off
REM Double-click this file to open the Niche Automation Script Hub menu.
REM
REM The first time, it sets everything up by itself (needs internet, about a
REM minute): it downloads "uv", a small free tool that fetches a private copy
REM of Python. Everything is stored inside this folder, in ".uv" and ".venv",
REM so nothing else on your computer changes. Delete the folder to remove it all.
REM
REM If that download is blocked (some work computers), it uses Python from
REM python.org instead, if it is installed.
setlocal
title Niche Automation Script Hub
cd /d "%~dp0"

set "UV_VERSION=0.13.7"
set "UV_INSTALL_DIR=%CD%\.uv"
set "UV_PYTHON_INSTALL_DIR=%CD%\.uv\python"
set "UV_CACHE_DIR=%CD%\.uv\cache"
set "UV_NO_MODIFY_PATH=1"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV=%UV_INSTALL_DIR%\uv.exe"

REM A toolbox that no longer starts (for example, the folder was moved) is rebuilt
if exist ".venv\" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul || rmdir /s /q ".venv"
)
if exist ".venv\Scripts\python.exe" goto run

echo.
echo  Setting up for the first time. This needs internet and takes about a minute...
echo.

if not exist "%UV%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/%UV_VERSION%/install.ps1 | iex" >nul
)
if exist "%UV%" (
    "%UV%" venv --seed --python 3.12 ".venv"
)

if not exist ".venv\Scripts\python.exe" call :use_installed_python
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Sorry, the automatic setup did not work. Usually this means there is no
    echo  internet connection, or a work network is blocking the download.
    echo.
    echo  Fix: install Python from python.org - tick "Add python.exe to PATH" -
    echo  then double-click this file again. Opening the download page now...
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

:run
".venv\Scripts\python.exe" start.py
echo.
pause
exit /b 0

:use_installed_python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if defined PY (
    echo  Using the Python already installed on this computer...
    %PY% -m venv ".venv"
)
exit /b 0

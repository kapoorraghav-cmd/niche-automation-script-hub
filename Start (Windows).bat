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

if not exist "%UV%" call :download_uv
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

:download_uv
REM Download uv's official Windows release from GitHub and check its
REM fingerprint (SHA-256) before unpacking it into .uv
set "UV_ARCH=x86_64"
set "UV_SHA256=0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "UV_ARCH=aarch64"
    set "UV_SHA256=505d9e65e7692bac3ddf98c66754aa26c5050c409c184af30a881a0a72cc85e3"
)
set "UV_ZIP_URL=https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-%UV_ARCH%-pc-windows-msvc.zip"
set "UV_ZIP=%TEMP%\niche-hub-uv.zip"
REM Only built-in .NET features are used, so this works on every Windows 10/11
REM (some PowerShell add-on commands go missing on computers with PowerShell 7)
set "PSModulePath="
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
  "(New-Object Net.WebClient).DownloadFile($env:UV_ZIP_URL, $env:UV_ZIP);" ^
  "$stream = [IO.File]::OpenRead($env:UV_ZIP);" ^
  "$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($stream)).Replace('-', '');" ^
  "$stream.Close();" ^
  "if ($hash -ne $env:UV_SHA256) { [IO.File]::Delete($env:UV_ZIP); throw 'The download did not match its fingerprint.' };" ^
  "if ([IO.Directory]::Exists($env:UV_INSTALL_DIR)) { [IO.Directory]::Delete($env:UV_INSTALL_DIR, $true) };" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "[IO.Compression.ZipFile]::ExtractToDirectory($env:UV_ZIP, $env:UV_INSTALL_DIR);" ^
  "[IO.File]::Delete($env:UV_ZIP)"
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

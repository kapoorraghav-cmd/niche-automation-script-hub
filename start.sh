#!/bin/bash
# Linux: run ./start.sh to open the Niche Automation Script Hub menu.
#
# The first time, it sets everything up by itself (needs internet): it
# downloads "uv", which fetches a private copy of Python. Everything is stored
# inside this folder, in ".uv" and ".venv". If that fails, it uses an installed
# python3 instead.
cd "$(dirname "$0")" || exit 1

UV_VERSION="0.13.7"
export UV_INSTALL_DIR="$PWD/.uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv/python"
export UV_CACHE_DIR="$PWD/.uv/cache"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_PREFERENCE=only-managed
UV="$UV_INSTALL_DIR/uv"

if [ -d ".venv" ] && ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up for the first time. This needs internet and takes about a minute..."
    if [ ! -x "$UV" ]; then
        if command -v curl >/dev/null 2>&1; then
            curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh >/dev/null 2>&1
        elif command -v wget >/dev/null 2>&1; then
            wget -qO- "https://astral.sh/uv/$UV_VERSION/install.sh" | sh >/dev/null 2>&1
        fi
    fi
    [ -x "$UV" ] && "$UV" venv --seed --python 3.12 .venv
    if [ ! -x ".venv/bin/python" ] && command -v python3 >/dev/null 2>&1; then
        echo "Using the installed python3..."
        python3 -m venv .venv
    fi
    if [ ! -x ".venv/bin/python" ]; then
        echo "Setup did not work. Check your internet connection, or install Python:"
        echo "  sudo apt install python3 python3-venv python3-pip"
        exit 1
    fi
fi

exec .venv/bin/python start.py

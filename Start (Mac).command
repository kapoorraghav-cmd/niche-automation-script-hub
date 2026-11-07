#!/bin/bash
# Double-click this file to open the Niche Automation Script Hub menu.
#
# The first time, it sets everything up by itself (needs internet, about a
# minute): it downloads "uv", a small free tool that fetches a private copy of
# Python. Everything is stored inside this folder, in ".uv" and ".venv", so
# nothing else on your Mac changes. Delete the folder to remove it all.
#
# If macOS says this file "cannot be opened", right-click it and choose Open
# (or allow it in System Settings > Privacy & Security).
cd "$(dirname "$0")" || exit 1

UV_VERSION="0.13.7"
export UV_INSTALL_DIR="$PWD/.uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv/python"
export UV_CACHE_DIR="$PWD/.uv/cache"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_PREFERENCE=only-managed
UV="$UV_INSTALL_DIR/uv"

# A toolbox that no longer starts (for example, the folder was moved) is rebuilt
if [ -d ".venv" ] && ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
    echo ""
    echo "  Setting up for the first time. This needs internet and takes about a minute..."
    echo ""
    if [ ! -x "$UV" ]; then
        curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh >/dev/null 2>&1
    fi
    if [ -x "$UV" ]; then
        "$UV" venv --seed --python 3.12 .venv
    fi
    # Fallback: a Python that is already installed (from python.org or Homebrew)
    if [ ! -x ".venv/bin/python" ] && command -v python3 >/dev/null 2>&1; then
        echo "  Using the Python already installed on this Mac..."
        python3 -m venv .venv
    fi
    if [ ! -x ".venv/bin/python" ]; then
        echo ""
        echo "  Sorry, the automatic setup did not work. Usually this means there is no"
        echo "  internet connection, or a work network is blocking the download."
        echo ""
        echo "  Fix: install Python from python.org, then double-click this file again."
        echo "  Opening the download page now..."
        open "https://www.python.org/downloads/"
        read -r -p "Press Enter to close this window..."
        exit 1
    fi
fi

.venv/bin/python start.py
echo ""
read -r -p "Press Enter to close this window..." || true

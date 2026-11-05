#!/bin/bash
# Linux: run ./start.sh to open the Niche Automation Script Hub menu.
# The first time, it sets up a private "toolbox" (.venv) for the hub.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python is not installed. On Ubuntu/Debian run:"
    echo "  sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up for the first time. This takes about a minute..."
    python3 -m venv .venv || {
        echo "Could not create the toolbox. Try: sudo apt install python3-venv"
        exit 1
    }
    .venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
fi

exec .venv/bin/python start.py

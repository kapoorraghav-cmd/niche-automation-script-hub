#!/bin/bash
# Double-click this file to open the Niche Automation Script Hub menu.
# The first time, it sets up a private "toolbox" (.venv) for the hub.
# If macOS says it "cannot be opened", right-click it and choose Open.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  Python is not installed yet."
    echo "  Opening the download page. Install it, then double-click this file again."
    echo ""
    open "https://www.python.org/downloads/"
    read -r -p "Press Enter to close this window..."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up for the first time. This takes about a minute..."
    if ! python3 -m venv .venv; then
        echo ""
        echo "  Could not set up the toolbox. Please install Python from python.org"
        read -r -p "Press Enter to close this window..."
        exit 1
    fi
    .venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
fi

.venv/bin/python start.py
echo ""
read -r -p "Press Enter to close this window..."

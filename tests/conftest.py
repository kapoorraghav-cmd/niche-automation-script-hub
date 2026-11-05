"""Shared test setup: every test runs inside its own empty temporary folder."""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An empty folder that acts like the project folder for one test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_script(script_name: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run a tool the same way a user would: python <script> in a terminal."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script_name)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )

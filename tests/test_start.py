"""Tests for start.py, the "Start here" menu."""

import os
import subprocess
import sys

import pytest

import start
from conftest import PROJECT_ROOT


def run_menu(workspace, answers):
    """Run the menu like a user, typing each answer followed by Enter."""
    env = dict(os.environ, NICHE_HUB_NO_OPEN="1", NICHE_HUB_WORK_FOLDER=str(workspace))
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "start.py")],
        input="".join(answer + "\n" for answer in answers),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def tool_number(script):
    return str([tool.script for tool in start.ALL_TOOLS].index(script) + 1)


def test_every_tool_in_the_menu_exists():
    for tool in start.ALL_TOOLS:
        assert (PROJECT_ROOT / tool.script).exists(), tool.script


def test_every_tool_script_is_in_the_menu():
    menu_scripts = {tool.script for tool in start.ALL_TOOLS}
    skip = {"start.py"}
    for path in PROJECT_ROOT.glob("*.py"):
        if path.name not in skip:
            assert path.name in menu_scripts, f"{path.name} is missing from the menu"


def test_every_package_comes_from_requirements_txt():
    known = start.requirement_lines()
    for tool in start.ALL_TOOLS:
        for package in tool.packages:
            assert package.lower() in known, f"{package} ({tool.script}) is not in requirements.txt"


def test_requirement_lines_keep_version_ranges():
    known = start.requirement_lines()
    assert known["pillow"].startswith("Pillow>=")
    assert "<" in known["av"]


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("/Users/me/Downloads", "/Users/me/Downloads"),
        ('"C:\\Users\\Me\\My Files"', "C:\\Users\\Me\\My Files"),
        ("'/Users/me/My Files'", "/Users/me/My Files"),
        ("  /tmp/x  ", "/tmp/x"),
    ],
)
def test_dragged_folder_paths_are_cleaned(typed, expected):
    assert start.clean_dragged_path(typed) == expected


@pytest.mark.skipif(sys.platform.startswith("win"), reason="backslash-space is a Mac/Linux terminal habit")
def test_mac_style_escaped_spaces_are_cleaned():
    assert start.clean_dragged_path("/Users/me/My\\ Files") == "/Users/me/My Files"


def test_menu_lists_every_tool_and_quits(workspace):
    result = run_menu(workspace, ["q"])

    assert result.returncode == 0, result.stderr
    for tool in start.ALL_TOOLS:
        assert tool.name in result.stdout
    assert "Bye!" in result.stdout


def test_wrong_choice_asks_again(workspace):
    result = run_menu(workspace, ["99", "hello", "q"])

    assert result.stdout.count("Please type a number from 1 to") == 2


def test_choosing_a_tool_creates_its_folder_and_runs_it(workspace):
    number = tool_number("bulk_renamer.py")
    # tool number, Enter (no undo), Enter (ready), Enter (back to menu), quit
    result = run_menu(workspace, [number, "", "", "n", "", "q"])

    assert result.returncode == 0, result.stderr
    assert (workspace / "files_to_rename").is_dir()
    assert "You chose: Bulk File Renamer" in result.stdout
    assert "Tool: Bulk File Renamer" in result.stdout  # the tool itself ran


def test_going_back_does_not_run_the_tool(workspace):
    number = tool_number("bulk_renamer.py")
    result = run_menu(workspace, [number, "", "b", "", "q"])

    assert "Tool: Bulk File Renamer" not in result.stdout

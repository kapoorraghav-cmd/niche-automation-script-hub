#!/usr/bin/env python3
"""
Start Here — the Niche Automation Script Hub menu
==================================================
A simple numbered menu for every tool in the hub, so you never have to
remember a script name. Pick a tool and this menu will:

  1. Install the free add-on libraries that tool needs (only the first time)
  2. Open the tool's folder so you can drop your files in
  3. Run the tool
  4. Offer to open the folder with your results

The easiest way to start it is to double-click "Start (Windows).bat",
"Start (Mac).command", or run "start.sh" on Linux. You can also type:

    python start.py
"""

# ---------------------------------------------------------------------------
# Imports — everything here is built into Python, so this menu always works
# ---------------------------------------------------------------------------

import importlib.util  # Lets us check whether a library is installed
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Optional


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

PROJECT_FOLDER = Path(__file__).resolve().parent

# Where the tools' input/output folders live. Normally the project folder;
# the automated tests point this at a temporary folder instead.
WORK_FOLDER = Path(os.environ.get("NICHE_HUB_WORK_FOLDER", PROJECT_FOLDER))


class Tool(NamedTuple):
    name: str
    script: str
    description: str
    # Python module names to check, and the matching names in requirements.txt
    modules: tuple
    packages: tuple
    # What the user should do before the tool runs (shown as "Step 1")
    instructions: str
    # Folder to open for the user before running, and where results appear
    input_folder: Optional[str]
    output_folder: Optional[str]
    # Extra abilities: "undo" for tools with --undo, "folder" for tools that
    # can check any folder you choose
    extras: tuple = ()
    note: str = ""


CATEGORIES = [
    ("Pictures", [
        Tool("Image Compressor & Converter", "image_compressor.py",
             "Shrink JPG/PNG photos to small .webp files that still look great",
             ("PIL",), ("Pillow",),
             "Put your photos (.jpg, .png) in the folder below.",
             "input_images", "optimized_images"),
        Tool("Background Remover", "background_remover.py",
             "Cut the background out of product photos and headshots",
             ("onnxruntime", "numpy", "PIL"), ("onnxruntime", "numpy", "Pillow"),
             "Put your photos (.jpg, .png, .webp) in the folder below.",
             "input_photos", "no_background",
             note="The first run downloads the picture model (about 170 MB, once)."),
    ]),
    ("Documents", [
        Tool("PDF Text & Image Extractor", "pdf_extractor.py",
             "Pull the text and pictures out of PDF files",
             ("pypdf", "PIL"), ("pypdf", "Pillow"),
             "Put your PDF files in the folder below.",
             "input_pdfs", "extracted_pdfs"),
        Tool("Scanned Document Reader (OCR)", "ocr_reader.py",
             "Read the words in scanned PDFs, photos of documents and screenshots",
             ("rapidocr", "pypdfium2", "pypdf", "PIL"), ("rapidocr", "onnxruntime", "pypdfium2", "pypdf", "Pillow"),
             "Put your scans, photos or screenshots in the folder below.",
             "input_scans", "scanned_text",
             note="The first run downloads small text-reading models (once)."),
        Tool("Mail-Merge Certificates & Letters", "mail_merge.py",
             "Make one personalised Word/PDF document per row of a spreadsheet",
             ("docxtpl", "pandas", "openpyxl"), ("docxtpl", "pandas", "openpyxl", "xlrd"),
             "Put ONE Word template and ONE spreadsheet in the folder below "
             "(the first run creates an example of each for you to copy).",
             "mail_merge", "merged_documents"),
    ]),
    ("Spreadsheets", [
        Tool("Spreadsheet Cleaner", "excel_cleaner.py",
             "Remove duplicate rows and fix messy dates in Excel/CSV files",
             ("pandas", "openpyxl", "xlrd"), ("pandas", "openpyxl", "xlrd"),
             "Put your Excel or CSV files in the folder below.",
             "input_spreadsheets", "cleaned_spreadsheets"),
        Tool("Spreadsheet Merger", "spreadsheet_merger.py",
             "Combine many Excel/CSV files into one spreadsheet",
             ("pandas", "openpyxl", "xlrd"), ("pandas", "openpyxl", "xlrd"),
             "Put all the Excel or CSV files you want combined in the folder below.",
             "spreadsheets_to_merge", "merged_spreadsheets"),
    ]),
    ("Audio & video", [
        Tool("Audio-to-Text Transcriber", "audio_transcriber.py",
             "Turn meeting recordings and voice memos into written transcripts",
             ("faster_whisper",), ("faster-whisper", "av"),
             "Put your recordings (.mp3, .m4a, .wav, ...) in the folder below.",
             "input_audio", "transcripts",
             note="The first run downloads the speech model (about 145 MB, once)."),
        Tool("Video Subtitle Maker", "video_subtitles.py",
             "Create subtitle files (.srt and .vtt) for your videos",
             ("faster_whisper",), ("faster-whisper", "av"),
             "Put your videos (.mp4, .mov, ...) in the folder below.",
             "input_videos", "subtitles",
             note="The first run downloads the speech model (about 145 MB, once)."),
        Tool("Meeting Notes Summarizer", "meeting_summarizer.py",
             "Turn transcripts into a summary, decisions and action items",
             (), (),
             "It reads the transcripts made by the Audio-to-Text Transcriber "
             "(you can also drop .txt notes in the folder below).",
             "transcripts", "meeting_notes",
             note="Needs the free Ollama app from https://ollama.com (see the guide)."),
    ]),
    ("Files & web", [
        Tool("Bulk File Renamer", "bulk_renamer.py",
             "Rename hundreds of files to tidy numbered names (with undo)",
             (), (),
             "Put the files you want renamed in the folder below.",
             "files_to_rename", "files_to_rename", extras=("undo",)),
        Tool("Duplicate File Finder", "duplicate_finder.py",
             "Find duplicate files and move the extra copies aside (never deletes)",
             ("PIL",), ("Pillow",),
             "Put files in the folder below, or choose any folder to check.",
             "files_to_check", None, extras=("undo", "folder")),
        Tool("Website-to-Markdown Scraper", "web_scraper.py",
             "Save web articles as clean Markdown files, without the ads",
             ("trafilatura",), ("trafilatura",),
             "You'll be asked to paste a link (or put many links in urls.txt).",
             None, "scraped_articles"),
    ]),
]

ALL_TOOLS = [tool for _, tools in CATEGORIES for tool in tools]

# Set NICHE_HUB_NO_OPEN=1 to stop the menu opening folder windows (used by
# the automated tests, which run without a screen).
OPEN_FOLDERS = os.environ.get("NICHE_HUB_NO_OPEN") != "1"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def ask(question: str) -> str:
    """Ask a question; treat a closed input (end of file) as 'quit'."""
    try:
        return input(question).strip()
    except EOFError:
        return "q"


def print_menu() -> None:
    print()
    print("=" * 60)
    print("  Niche Automation Script Hub — Start here")
    print("=" * 60)
    number = 1
    for category, tools in CATEGORIES:
        print()
        print(f"  {category}")
        for tool in tools:
            print(f"   {number:>2}. {tool.name}")
            print(f"       {tool.description}")
            number += 1
    print()
    print("    q. Quit")
    print()


def requirement_lines() -> dict:
    """
    Read requirements.txt into {package name: full line}, so the menu installs
    exactly the same versions as `pip install -r requirements.txt` would.
    """
    lines = {}
    path = PROJECT_FOLDER / "requirements.txt"
    if not path.exists():
        return lines
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if match:
            lines[match.group(1).lower().replace("_", "-")] = line
    return lines


def missing_modules(tool: Tool) -> list:
    return [name for name in tool.modules if importlib.util.find_spec(name) is None]


def bundled_uv() -> Optional[Path]:
    """The copy of uv the double-click launchers download into .uv, if any."""
    name = "uv.exe" if sys.platform.startswith("win") else "uv"
    path = PROJECT_FOLDER / ".uv" / name
    return path if path.exists() else None


def install_command(specs: list) -> list:
    """
    Use the launchers' uv when it's there (it installs several times faster
    than pip); otherwise use Python's own installer, pip.
    """
    uv = bundled_uv()
    if uv:
        return [str(uv), "pip", "install", "--python", sys.executable, *specs]
    return [sys.executable, "-m", "pip", "install", *specs]


def install_packages(tool: Tool) -> bool:
    """Install the tool's libraries (with the versions from requirements.txt)."""
    known = requirement_lines()
    specs = [known.get(name.lower(), name) for name in tool.packages]
    print()
    print(f"Installing: {', '.join(tool.packages)}")
    print("This happens only once and can take a few minutes. Please wait...")
    print()
    result = subprocess.run(install_command(specs))
    if result.returncode != 0:
        print()
        print("⚠️  The installation didn't finish. Check your internet connection")
        print("   and try again. You can also run:  pip install -r requirements.txt")
        return False
    importlib.invalidate_caches()
    return True


def open_folder(folder: Path) -> None:
    """Open a folder in Finder / File Explorer / the Linux file manager."""
    if not OPEN_FOLDERS:
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass  # Not being able to open a window is never a reason to stop


def clean_dragged_path(text: str) -> str:
    """
    Turn a folder dragged into the terminal into a normal path.
    Mac terminals write "My\\ Folder", Windows writes "C:\\My Folder" in quotes.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if "\\ " in text and not sys.platform.startswith("win"):
        try:
            return " ".join(shlex.split(text))
        except ValueError:
            pass
    return text


def run_tool(tool: Tool, extra_args: list) -> None:
    print()
    print("-" * 60)
    subprocess.run([sys.executable, str(PROJECT_FOLDER / tool.script), *extra_args],
                   cwd=WORK_FOLDER)
    print("-" * 60)


def use_tool(tool: Tool) -> None:
    print()
    print(f"You chose: {tool.name}")
    print(f"  {tool.description}")
    if tool.note:
        print(f"  Note: {tool.note}")

    if not (PROJECT_FOLDER / tool.script).exists():
        print()
        print(f"⚠️  {tool.script} is missing from this folder. Download the hub again.")
        return

    # 1) Make sure the tool's libraries are installed
    missing = missing_modules(tool)
    if missing:
        print()
        print("This tool needs a few free add-on libraries that aren't installed yet.")
        if ask("Install them now? Type y to continue: ").lower() not in {"y", "yes"}:
            print("No problem — nothing was installed.")
            return
        if not install_packages(tool):
            return

    extra_args: list = []

    # 2) Undo option for tools that support it
    if "undo" in tool.extras:
        choice = ask("\nType u to UNDO the last run, or just press Enter to continue: ")
        if choice.lower() == "u":
            run_tool(tool, ["--undo"])
            return

    # 3) Show where the files go and open the folder
    print()
    print(f"Step 1: {tool.instructions}")
    if tool.input_folder:
        folder = WORK_FOLDER / tool.input_folder
        folder.mkdir(exist_ok=True)
        print(f"        Folder: {folder}")
        if OPEN_FOLDERS:
            print("        (Opening it for you now...)")
        open_folder(folder)

    if "folder" in tool.extras:
        print()
        print("        To check a different folder instead (e.g. Downloads), drag it")
        print("        into this window now, or type its path.")
        answer = ask("Step 2: Press Enter when you're ready (or b to go back): ")
        if answer.lower() == "b" or answer.lower() == "q":
            return
        if answer:
            extra_args.append(clean_dragged_path(answer))
    else:
        answer = ask("Step 2: Press Enter when you're ready (or b to go back): ")
        if answer.lower() in {"b", "q"}:
            return

    # 4) Run it
    run_tool(tool, extra_args)

    # 5) Offer to open the results
    if tool.output_folder and OPEN_FOLDERS:
        results = WORK_FOLDER / tool.output_folder
        if results.exists():
            answer = ask("\nOpen the results folder? Press Enter for yes, or n for no: ")
            if answer.lower() not in {"n", "no", "q"}:
                open_folder(results)


# ---------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if sys.version_info < (3, 9):
        print("This hub needs Python 3.10 or newer. Download it from https://www.python.org/downloads/")
        raise SystemExit(1)

    while True:
        print_menu()
        choice = ask(f"Type a number (1-{len(ALL_TOOLS)}) and press Enter: ").lower()
        if choice in {"q", "quit", "exit"}:
            print("\nBye! Run me again any time.")
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(ALL_TOOLS):
            print(f"\nPlease type a number from 1 to {len(ALL_TOOLS)}, or q to quit.")
            continue
        use_tool(ALL_TOOLS[int(choice) - 1])
        ask("\nPress Enter to go back to the menu...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped. Bye!")

#!/usr/bin/env python3
"""
Record the animated demos (GIFs) used in the README and tool guides.

Each demo prepares sample files in a temporary folder, then records a REAL
terminal session with VHS (https://github.com/charmbracelet/vhs) while the
tool runs. Nothing is faked: what you see is what the tool prints.

    brew install vhs        # or see the VHS website for Windows/Linux
    pip install -r requirements-dev.txt
    python docs/make_gifs.py              # all demos
    python docs/make_gifs.py renamer      # just one

Needs an internet connection for the sample photo (picsum.photos, Unsplash
License, free to use) and the macOS `say` command for the sample recording.
"""

import io
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GIF_DIR = PROJECT_ROOT / "docs" / "gifs"
SAMPLE_PHOTO_URL = "https://picsum.photos/id/0/4032/2688.jpg"

TAPE_SETTINGS = """\
Set Shell "bash"
Set FontSize 17
Set Width 1200
Set Height {height}
Set Padding 24
Set Theme "Dracula"
Set TypingSpeed 45ms
Set WindowBar Colorful
"""


# ---------------------------------------------------------------------------
# Sample files for each demo
# ---------------------------------------------------------------------------

def sample_photos(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SAMPLE_PHOTO_URL, timeout=60) as response:
        photo = Image.open(io.BytesIO(response.read())).convert("RGB")
    photo.save(folder / "desk_photo.jpg", quality=95)
    logo = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse((100, 100, 1100, 1100), fill=(56, 189, 248, 255))
    logo.save(folder / "team_logo.png")


def sample_camera_files(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ["DCIM_9.JPG"] + [f"DCIM_{n:05d}.JPG" for n in range(412, 424)]:
        (folder / name).write_bytes(b"photo")


def sample_recording(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    script = (
        "Good morning everyone, let's keep this stand-up short. "
        "Yesterday I finished the budget spreadsheet and sent it to finance. "
        "Today I'm updating the client presentation for Thursday."
    )
    aiff = folder.parent / "standup.aiff"
    subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", str(aiff), script], check=True)
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(folder / "team_standup.m4a")], check=True)
    aiff.unlink()


# ---------------------------------------------------------------------------
# The demos: (prepare function, what to type, terminal height, pauses)
# ---------------------------------------------------------------------------

def start_menu(workspace: Path) -> str:
    sample_photos(workspace / "input_images")
    return """
Type "python start.py"
Enter
Sleep 2.5s
Type "1"
Sleep 600ms
Enter
Sleep 2s
Enter
Sleep 9s
Enter
Sleep 2s
Type "q"
Enter
Sleep 2s
"""


def renamer(workspace: Path) -> str:
    sample_camera_files(workspace / "files_to_rename")
    return """
Type "ls files_to_rename"
Enter
Sleep 2s
Type "python bulk_renamer.py"
Enter
Sleep 2s
Type "Project Photos"
Sleep 500ms
Enter
Sleep 3s
Type "y"
Sleep 500ms
Enter
Sleep 3s
Type "ls files_to_rename"
Enter
Sleep 4s
"""


def image_compressor(workspace: Path) -> str:
    sample_photos(workspace / "input_images")
    return """
Type "python image_compressor.py"
Enter
Sleep 10s
"""


def audio_transcriber(workspace: Path) -> str:
    sample_recording(workspace / "input_audio")
    return """
Type "python audio_transcriber.py"
Enter
Sleep 14s
Type "cat transcripts/team_standup.txt"
Enter
Sleep 6s
"""


DEMOS = {
    "start_menu": (start_menu, 1150),
    "renamer": (renamer, 1000),
    "image_compressor": (image_compressor, 720),
    "audio_transcriber": (audio_transcriber, 1000),
}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def demo_workspace() -> Path:
    """A tidy-looking folder for the recording (paths appear on screen)."""
    shared = Path("/Users/Shared")
    base = shared if shared.is_dir() else Path(tempfile.gettempdir())
    workspace = base / "Niche Automation Script Hub"
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir()
    return workspace


def record(name: str) -> None:
    prepare, height = DEMOS[name]
    workspace = demo_workspace()
    try:
        steps = prepare(workspace)
        output = GIF_DIR / f"{name}.gif"
        tape = TAPE_SETTINGS.format(height=height) + textwrap.dedent(f"""
            Output "{output}"
            Hide
            Type "cd '{workspace}' && export PS1='$ ' NICHE_HUB_NO_OPEN=1 && alias python='{sys.executable}' && cp -R '{PROJECT_ROOT}'/*.py . && clear"
            Enter
            Sleep 500ms
            Show
        """) + steps
        tape_path = workspace / f"{name}.tape"
        tape_path.write_text(tape, encoding="utf-8")
        subprocess.run(["vhs", str(tape_path)], check=True, cwd=workspace)
        print(f"  saved {output.relative_to(PROJECT_ROOT)} ({output.stat().st_size // 1024} KB)")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> None:
    if not shutil.which("vhs"):
        raise SystemExit("VHS is not installed. See https://github.com/charmbracelet/vhs")
    GIF_DIR.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[1:] or list(DEMOS):
        print(f"Recording {name} ...")
        record(name)


if __name__ == "__main__":
    main()

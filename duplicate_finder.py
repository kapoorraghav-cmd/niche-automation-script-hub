#!/usr/bin/env python3
r"""
Duplicate File Finder
=====================
This script looks through a folder (and every folder inside it) for files
that are exact copies of each other, for example:

    report.pdf     and   report (1).pdf
    IMG_2041.jpg   and   Old phone backup/IMG_2041 copy.jpg

It keeps one copy of each file and MOVES the extra copies into a
"duplicates_review" folder, so you can look them over before deleting them
yourself. It also spots photos that look the same even though the files are
different (a resized, recompressed or converted copy) and lists them in a
report.

This tool NEVER deletes anything. To keep it safe, it:

  1. Shows you what it found and only moves files after you type y
  2. Copies each file's folder layout into the review folder, so nothing is
     overwritten or mixed up
  3. Saves an "undo log" so you can put every file back later

How to run (after following README.md):
    python duplicate_finder.py

That checks the "files_to_check" folder. To check another folder instead,
type its path after the script name (use quotes if it contains spaces):
    python duplicate_finder.py ~/Downloads
    python duplicate_finder.py "C:\Users\Sam\My Pictures"

To put every moved file back:
    python duplicate_finder.py --undo
"""

# ---------------------------------------------------------------------------
# Imports — all built into Python, plus Pillow for comparing photos
# ---------------------------------------------------------------------------

import csv  # Writes the report and the undo log (small spreadsheet-style files)
import hashlib  # Makes a "fingerprint" of a file's contents to spot exact copies
import os  # Low-level "move this file" and "list this folder" commands
import stat  # Tells normal files apart from shortcuts, hidden files, etc.
import sys  # Gives access to the terminal output settings and the options you type
import tempfile  # Finds your computer's temporary folder (see safety checks)
import warnings  # Lets us silence Pillow's warning about very large pictures
from collections import defaultdict  # A dictionary that starts each new entry as an empty list
from pathlib import Path, PureWindowsPath  # Easy, cross-platform file and folder paths
from typing import Callable, NamedTuple, Optional

# Pillow (installed via: pip install Pillow) is only needed for the
# "similar photos" check. Exact copies are found without it, so the tool
# still works if Pillow is missing — it just skips that one check.
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# The folder that is checked when you don't type a folder path yourself
FOLDER_NAME = "files_to_check"

# Extra copies are moved into a folder with this name, created NEXT TO the
# folder being checked (for files_to_check, that is right here in the
# project). Inside it, every file keeps its folder layout, so
# Downloads/Taxes/report.pdf is moved to
# duplicates_review/Downloads/Taxes/report.pdf.
REVIEW_FOLDER_NAME = "duplicates_review"

# The report is always saved in the folder you run the script from (this
# project folder), so it is easy to find and never ends up mixed in with
# the files being checked. It is replaced each time you run the tool.
REPORT_NAME = "duplicates_report.csv"

# The undo log lives inside the review folder. The dot at the start hides it
# on Mac and Linux. When you delete the review folder, the log goes too,
# which is right: by then there is nothing left to put back.
UNDO_LOG_NAME = ".duplicates_undo_log.csv"

# A tiny note, saved where you run the script, that remembers which review
# folder was used last. That's how a plain  python duplicate_finder.py --undo
# also works after checking another folder, like your Downloads.
LAST_RUN_NOTE = ".duplicates_last_run.txt"

# Which file of a set of exact copies stays where it is:
#   "oldest"        — the file with the oldest "last modified" date. Usually
#                     the original: downloading or saving a file again gives
#                     the new copy today's date.
#   "newest"        — the most recently modified file.
#   "shortest_path" — the file with the fewest folders in its path, then the
#                     shortest name. Keeps "report.pdf" rather than
#                     "Backup/Old/report (1).pdf".
# When files are equal by this rule, the shortest path wins, then A-to-Z order,
# so the same files always give the same result.
KEEP = "oldest"

# Also look for photos that LOOK the same but are not byte-for-byte copies:
# a resized, recompressed or converted copy (photo.png and photo.jpg).
CHECK_SIMILAR_PHOTOS = True

# Similar photos are only LISTED in the report, not moved. "Looks the same"
# can be wrong: burst shots or two photos taken a second apart can look
# almost identical to a computer, and you may want to keep both. Look at the
# report and decide yourself. Set this to True to move them too (the
# sharpest version — the one with the most pixels — is always kept).
MOVE_SIMILAR_PHOTOS = False

# How alike two photos must be to count as "similar". Each photo is shrunk
# to a tiny grid and turned into 64 light/dark checks (see photo_fingerprint
# below). This is how many of those 64 checks may differ.
#   0     — only near-perfect matches
#   5     — resized, recompressed and converted copies (recommended)
#   10+   — starts matching photos that are merely alike. Maximum 20.
SIMILARITY_THRESHOLD = 5

# Picture file types that are compared for similarity. (Exact copies are
# found for EVERY kind of file, pictures included.)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# Pictures that are almost one flat color (blank pages, plain backgrounds)
# all look alike to the similarity check, so they are skipped. This is the
# smallest difference between the lightest and darkest spot (0–255) a
# picture needs to be compared.
MIN_PHOTO_DETAIL = 10

# Similar photos must have the same shape (width compared to height),
# allowing this much difference for rounding (0.05 = 5%).
SHAPE_TOLERANCE = 0.05

# How many moves to list in the preview before asking
PREVIEW_LINES = 10

# How many of the biggest groups to list in the summary
TOP_GROUPS = 5

# For big folders, print a progress line after every this many files
PROGRESS_EVERY = 500

# For the quick first check we only read this much from the start and the
# end of each file (64 KB). Only files that pass are read in full.
QUICK_CHECK_BYTES = 64 * 1024

# Files are read in pieces of this size, so even huge videos don't fill up
# your computer's memory
READ_CHUNK_BYTES = 1024 * 1024

# Windows and Mac create these helper files by themselves — never touched
SYSTEM_FILES = {"thumbs.db", "ehthumbs.db", "desktop.ini", "icon\r"}

# Files still being downloaded. Moving them would break the download.
UNFINISHED_DOWNLOAD_ENDINGS = {".crdownload", ".part", ".partial", ".download", ".opdownload"}

# Folders that are never looked inside. Moving files out of them could break
# software projects (node_modules), or they belong to the system.
SKIP_FOLDER_NAMES = {
    REVIEW_FOLDER_NAME,
    "node_modules",
    "__pycache__",
    "$recycle.bin",
    "system volume information",
}

# On a Mac, some "files" are really folders in disguise ("packages"), such as
# apps and the Photos library. Rearranging what's inside them would damage
# them, so they are skipped completely.
PACKAGE_FOLDER_ENDINGS = {
    ".app", ".photoslibrary", ".migratedphotolibrary", ".aplibrary", ".musiclibrary",
    ".tvlibrary", ".imovielibrary", ".fcpbundle", ".lrdata", ".lrlibrary", ".logicx",
    ".band", ".bundle", ".framework", ".plugin", ".kext", ".pkg", ".mpkg",
    ".xcodeproj", ".xcworkspace", ".pages", ".numbers", ".key", ".rtfd",
    ".sparsebundle", ".vmwarevm", ".pvm", ".utm",
}

# Never more than this, because higher values match unrelated photos
MAX_SIMILARITY_THRESHOLD = 20

# The EXIF tag where phones store "rotate me" information
ORIENTATION_TAG = 0x0112


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class FileInfo(NamedTuple):
    """One file found while scanning."""

    path: Path  # Full path to the file
    rel: Path  # Path inside the folder being checked, e.g. Taxes/report.pdf
    size: int  # Size in bytes
    mtime_ns: int  # "Last modified" time, in nanoseconds


class Group(NamedTuple):
    """A file to keep, plus its extra copies (or similar-looking photos)."""

    reason: str  # "exact" or "similar"
    keep: FileInfo
    extras: list[FileInfo]

    @property
    def extra_size(self) -> int:
        """Space the extra copies take up (what you could free)."""
        return sum(f.size for f in self.extras)


class Move(NamedTuple):
    """One planned move: an extra copy, its twin that stays, and where it goes."""

    source: FileInfo
    keep: FileInfo
    destination: Path
    reason: str  # "exact" or "similar"


class LogRow(NamedTuple):
    """
    One line of the undo log. "run" counts how many times files were moved.
    Paths are written relative to the folder that holds the review folder,
    with "/" between folders, so the log keeps working if you rename or move
    that whole folder.
    """

    run: int
    original: str
    review_copy: str


class ScanResult(NamedTuple):
    files: list[FileInfo]
    skipped: int  # Hidden, empty, system, unfinished and shortcut files
    unreadable: int  # Files or folders we weren't allowed to open


def format_size(num_bytes: int) -> str:
    """Turn a raw byte count into a friendly size like '142.3 KB' or '1.25 GB'."""
    if num_bytes < 1024:
        return f"{num_bytes} bytes"
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def plural(count: int, word: str, many: Optional[str] = None) -> str:
    """'1 file', '2 files', '1 copy', '3 copies' — with thousands separators."""
    if count == 1:
        return f"1 {word}"
    return f"{count:,} {many or word + 's'}"


def show_progress(done: int, total: int, verb: str, noun: str) -> None:
    """Print 'Checked 1,000 of 5,400 files...' every PROGRESS_EVERY files."""
    if PROGRESS_EVERY > 0 and done % PROGRESS_EVERY == 0 and done < total:
        print(f"   {verb} {done:,} of {total:,} {noun}...")


def ask_yes(question: str) -> bool:
    """Ask a yes/no question. Only "y" or "yes" counts as yes."""
    try:
        answer = input(question)
    except EOFError:
        # Nothing more can be typed (e.g. the input was piped in and ran out)
        return False
    return answer.strip().lower() in {"y", "yes"}


def ensure_folder() -> Path:
    """Make sure the files_to_check folder exists and return its path."""
    # Path(".") means "the folder where you ran the script from"
    folder = Path(".") / FOLDER_NAME

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {folder.resolve()}")
        print("   → Put the files you want to check in this folder, then run the script again.")
    else:
        print(f"📁 Found folder: {folder.resolve()}")
    print()

    return folder


# ---------------------------------------------------------------------------
# Choosing the folder (and refusing dangerous ones)
# ---------------------------------------------------------------------------

def clean_typed_path(text: str) -> Path:
    """
    Turn what was typed after the script name into a folder path.

    - Stray quote marks are removed. (On Windows, a path that ends in a
      backslash, like "D:\\My Photos\\", can keep its closing quote.)
    - "~" at the start means your home folder, like ~/Downloads. Most Mac
      and Linux terminals do this for you, but not inside quotes or on
      Windows, so we do it here as well.
    """
    cleaned = text.strip().strip("\"'").strip()
    return Path(os.path.expanduser(cleaned))


def folder_key(path: Path) -> tuple[str, ...]:
    """
    The folder names in a path, ignoring capital letters. Mac and Windows
    treat "Users" and "users" as the same folder; on Linux this is simply
    extra careful.
    """
    return tuple(part.casefold() for part in path.parts)


def is_inside(path: Path, folder: Path) -> bool:
    """True if path is the folder itself or anywhere inside it."""
    inner, outer = folder_key(path), folder_key(folder)
    return inner[: len(outer)] == outer


def protected_folders() -> tuple[list[Path], list[Path]]:
    """
    Folders this tool refuses to check.

    Returns (system_folders, container_folders):
      - system folders are refused together with everything inside them,
        because your computer or your apps depend on the files there
      - container folders (like /Users, which holds everyone's home
        folder) are only refused themselves; picking a folder inside
        them is fine
    """
    home = Path.home()
    system = [
        # Mac and Linux system folders
        "/System", "/Library", "/Applications", "/bin", "/sbin", "/usr", "/etc",
        "/boot", "/dev", "/proc", "/sys", "/lib", "/lib32", "/lib64", "/libx32",
        "/run", "/snap", "/root", "/cores", "/private/etc",
        # App data inside your home folder (settings, caches, mail, libraries)
        home / "Library", home / "Applications", home / "AppData",
    ]
    # Windows system folders. Windows tells programs where they are, so
    # they are found even if Windows isn't installed on drive C:.
    for name, fallback in (
        ("SystemRoot", r"C:\Windows"),
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("ProgramW6432", r"C:\Program Files"),
        ("ProgramData", r"C:\ProgramData"),
    ):
        system.append(os.environ.get(name, fallback))

    containers = [home.parent, "/Users", "/home", "/Volumes", "/var", "/private",
                  "/opt", "/mnt", "/media", "/srv", "/tmp"]

    def resolved(items: list) -> list[Path]:
        # resolve() follows shortcuts, e.g. on a Mac /etc is really /private/etc
        return [Path(item).resolve() for item in items]

    return resolved(system), resolved(containers)


def safety_problem(folder: Path) -> Optional[str]:
    """
    Return a friendly explanation if this folder is too dangerous to check,
    or None if it is fine.

    Moving "duplicate" files out of system or app folders could break your
    computer or your programs: apps often ship identical files on purpose.
    """
    target = folder.resolve()
    home = Path.home().resolve()

    if target == Path(target.anchor) or os.path.ismount(target):
        return (
            f"'{target}' is the top of a whole drive. Checking everything on it would\n"
            "   take ages and include system files. Please choose a folder inside it,\n"
            "   such as your Downloads or Pictures folder."
        )

    if target == home:
        return (
            "That is your whole home folder. It holds app settings and libraries (like\n"
            "   your Photos library or e-mail) that must not be rearranged. Please choose\n"
            "   one folder inside it, such as Downloads, Documents or Pictures."
        )

    if is_inside(home, target):
        return (
            f"'{target}' contains your whole home folder (and maybe other people's).\n"
            "   Please choose one folder inside your home folder, such as Downloads."
        )

    if REVIEW_FOLDER_NAME.casefold() in folder_key(target):
        return (
            f"That is (or is inside) a '{REVIEW_FOLDER_NAME}' folder, where this tool puts\n"
            "   the copies it moves. Check them there by eye, or put them back with --undo."
        )

    # Your temporary folder lives inside app data on Windows and inside a
    # system folder on Mac. Folders inside it (like a zip file you just
    # unpacked) are fine to check.
    # (Windows sometimes writes it in a short form like C:\Users\SAMSMI~1,
    # so both the written and the real form are compared.)
    for temp in {Path(tempfile.gettempdir()).absolute(), Path(tempfile.gettempdir()).resolve()}:
        for form in {folder.absolute(), target}:
            if is_inside(form, temp) and folder_key(form) != folder_key(temp):
                return None

    system, containers = protected_folders()
    for protected in system:
        if is_inside(target, protected):
            return (
                f"'{target}' is a system or app folder ({protected}).\n"
                "   Your computer or your programs need the files there exactly as they are,\n"
                "   so this tool won't touch it. Please choose a folder with your own files."
            )
    for protected in containers:
        if target == protected:
            return (
                f"'{target}' holds other big folders (drives, users or system files).\n"
                "   Please choose one folder inside it with your own files."
            )

    return None


def folder_from_arguments(words: list[str]) -> Optional[Path]:
    """
    Work out which folder the user typed. Returns None (after explaining)
    if it can't be found.
    """
    folder = clean_typed_path(" ".join(words))

    if len(words) > 1 and folder.is_dir():
        # The path had spaces but no quotes, so the terminal split it into
        # pieces. Joining them back worked, but tell the user for next time.
        print(f"Using the folder: {folder}")
        print("   (Tip: put quotes around folder paths that contain spaces.)")
        print()
        return folder

    if len(words) > 1:
        print(f"⚠️  Couldn't find a folder called: {folder}")
        print()
        print("If the folder name contains spaces, put quotes around the whole path:")
        print()
        print(f'    python duplicate_finder.py "{folder}"')
        print()
        return None

    if not folder.exists():
        print(f"⚠️  Couldn't find a folder called: {folder}")
        print()
        print("Tips:")
        print("  - Check the spelling (capital letters matter on some computers).")
        print("  - Easiest: type  python duplicate_finder.py  and a space, then drag the")
        print("    folder from your file browser into the terminal window to paste its path.")
        print("  - Put quotes around paths that contain spaces.")
        print()
        return None

    if not folder.is_dir():
        print(f"⚠️  That is a file, not a folder: {folder}")
        print("   Please type the path of the folder that contains your files.")
        print()
        return None

    print(f"📁 Found folder: {folder.resolve()}")
    print()
    return folder


# ---------------------------------------------------------------------------
# Step 1: list every file in the folder
# ---------------------------------------------------------------------------

def is_hidden(info: os.stat_result) -> bool:
    """True for files the computer marks as hidden (besides names starting with ".")."""
    # Windows "hidden" or "system" attribute
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
        return True
    # Mac "hidden" flag
    return bool(getattr(info, "st_flags", 0) & stat.UF_HIDDEN)


def is_link(info: os.stat_result) -> bool:
    """
    True for shortcuts (symlinks) and Windows "junctions". Following them
    could lead outside the folder, or round in a circle forever.
    """
    if stat.S_ISLNK(info.st_mode):
        return True
    junction = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    return junction is not None and getattr(info, "st_reparse_tag", None) == junction


def should_skip_folder(path: Path) -> bool:
    """True for sub-folders we never look inside."""
    name = path.name
    if name.startswith("."):
        return True
    if name.casefold() in SKIP_FOLDER_NAMES:
        return True
    if Path(name).suffix.casefold() in PACKAGE_FOLDER_ENDINGS:
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return True
    if is_link(info) or is_hidden(info):
        return True
    # A different drive plugged in "inside" this folder (common on Linux).
    # Files can't simply be moved between drives, so leave it alone.
    return os.path.ismount(path)


def should_skip_file(name: str, info: os.stat_result) -> bool:
    """True for files we never compare or move."""
    lowered = name.casefold()
    if name.startswith(".") or lowered in SYSTEM_FILES or lowered == REPORT_NAME.casefold():
        return True
    if Path(lowered).suffix in UNFINISHED_DOWNLOAD_ENDINGS:
        return True
    # Only normal files: no shortcuts, and no special system "files"
    if is_link(info) or not stat.S_ISREG(info.st_mode):
        return True
    if is_hidden(info):
        return True
    # Empty files are all "identical", but they take up no space
    return info.st_size == 0


def scan_folder(folder: Path) -> ScanResult:
    """List every file to compare in the folder and all its sub-folders."""
    files: list[FileInfo] = []
    skipped = 0
    unreadable = 0
    # A "hard link" is one file that appears in two places. Moving one of
    # them frees no space, so each real file is only counted once.
    seen: set[tuple[int, int]] = set()

    def count_unreadable(_error: OSError) -> None:
        nonlocal unreadable
        unreadable += 1

    for current, folder_names, file_names in os.walk(folder, onerror=count_unreadable):
        here = Path(current)
        # Sorting makes every run look at files in the same order
        folder_names[:] = [n for n in sorted(folder_names) if not should_skip_folder(here / n)]

        for name in sorted(file_names):
            path = here / name
            try:
                info = os.lstat(path)
            except OSError:
                unreadable += 1
                continue
            if should_skip_file(name, info):
                skipped += 1
                continue

            identity = (info.st_dev, info.st_ino)
            if info.st_ino and identity in seen:
                skipped += 1
                continue
            seen.add(identity)

            files.append(FileInfo(path, path.relative_to(folder), info.st_size, info.st_mtime_ns))
            if PROGRESS_EVERY > 0 and len(files) % (PROGRESS_EVERY * 10) == 0:
                print(f"   Found {len(files):,} files so far...")

    return ScanResult(files, skipped, unreadable)


# ---------------------------------------------------------------------------
# Step 2: find exact copies
# ---------------------------------------------------------------------------

def quick_fingerprint(path: Path, size: int) -> str:
    """
    A fast fingerprint made from only the start and end of the file.

    Files that differ almost always differ in their first or last 64 KB, so
    this rules out most look-alikes without reading huge files in full.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        digest.update(f.read(QUICK_CHECK_BYTES))
        if size > QUICK_CHECK_BYTES:
            f.seek(max(QUICK_CHECK_BYTES, size - QUICK_CHECK_BYTES))
            digest.update(f.read(QUICK_CHECK_BYTES))
    return digest.hexdigest()


def full_fingerprint(path: Path) -> str:
    """
    A SHA-256 fingerprint of the whole file. Two files with the same
    fingerprint have exactly the same contents (the chance of a mistake is
    far smaller than winning the lottery every day for a lifetime).
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for piece in iter(lambda: f.read(READ_CHUNK_BYTES), b""):
            digest.update(piece)
    return digest.hexdigest()


def group_by(
    files: list[FileInfo], fingerprint: Callable[[FileInfo], str], noun: str
) -> tuple[list[list[FileInfo]], int]:
    """
    Sort files into piles with the same fingerprint, with progress messages.
    Returns (piles with 2 or more files, how many files couldn't be read).
    """
    piles: dict[tuple[int, str], list[FileInfo]] = defaultdict(list)
    unreadable = 0
    total = len(files)
    for done, f in enumerate(files, start=1):
        try:
            piles[(f.size, fingerprint(f))].append(f)
        except OSError:
            # Locked, removed, or not allowed — skip it rather than stop
            unreadable += 1
        show_progress(done, total, "Checked", noun)
    return [pile for pile in piles.values() if len(pile) > 1], unreadable


def find_exact_copies(files: list[FileInfo]) -> tuple[list[list[FileInfo]], int]:
    """
    Find sets of files with exactly the same contents. Returns (sets, unreadable).

    Reading every byte of every file would be slow, so we narrow it down:
      1. Size: files of different sizes can't be copies (instant)
      2. Quick check: compare only the start and end of each file
      3. Full check: read the remaining candidates completely
    """
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for f in files:
        by_size[f.size].append(f)
    candidates = [f for pile in by_size.values() if len(pile) > 1 for f in pile]

    if not candidates:
        return [], 0

    print(f"Comparing {plural(len(candidates), 'file')} that share their size with another file...")
    piles, unreadable = group_by(
        candidates, lambda f: quick_fingerprint(f.path, f.size), "files"
    )
    print(f"   Checked {len(candidates):,} of {len(candidates):,} files.")

    # Small files were read completely by the quick check, so they're done
    done = [pile for pile in piles if pile[0].size <= 2 * QUICK_CHECK_BYTES]
    to_read = [f for pile in piles if pile[0].size > 2 * QUICK_CHECK_BYTES for f in pile]

    if to_read:
        print(f"Double-checking {plural(len(to_read), 'possible copy', 'possible copies')} byte by byte...")
        more, more_unreadable = group_by(to_read, lambda f: full_fingerprint(f.path), "files")
        print(f"   Checked {len(to_read):,} of {len(to_read):,} files.")
        done += more
        unreadable += more_unreadable
    print()

    return done, unreadable


def keep_rule() -> str:
    """The KEEP setting, falling back to "oldest" if it's misspelled."""
    if KEEP in {"oldest", "newest", "shortest_path"}:
        return KEEP
    print(f"⚠️  KEEP is set to '{KEEP}', which isn't 'oldest', 'newest' or 'shortest_path'.")
    print("   Keeping the oldest file of each set instead.")
    print()
    return "oldest"


def keep_order(rule: str) -> Callable[[FileInfo], tuple]:
    """
    Return a sorting key: the file that sorts FIRST in a set is kept.
    Ties are broken by the shortest path, then A-to-Z, so the result never
    depends on luck.
    """
    def key(f: FileInfo) -> tuple:
        text = str(f.rel)
        tie_break = (len(f.rel.parts), len(text), text.casefold(), text)
        if rule == "newest":
            return (-f.mtime_ns,) + tie_break
        if rule == "shortest_path":
            return tie_break + (f.mtime_ns,)
        return (f.mtime_ns,) + tie_break

    return key


# ---------------------------------------------------------------------------
# Step 3: find similar photos
# ---------------------------------------------------------------------------

class PhotoPrint(NamedTuple):
    """A photo's 64-check fingerprint plus its real size in pixels."""

    file: FileInfo
    bits: int
    width: int
    height: int


def flatten_to_gray(img: "Image.Image") -> "Image.Image":
    """Turn any picture into grayscale, placing see-through parts on white."""
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        picture = img.convert("RGBA")
        background = Image.new("RGBA", picture.size, (255, 255, 255, 255))
        background.alpha_composite(picture)
        img = background
    return img.convert("L")


def photo_fingerprint(f: FileInfo) -> Optional[PhotoPrint]:
    """
    Make a "difference hash" (dHash) of a photo, or None if it can't be read
    or is too plain to compare.

    How it works, in plain English:
      1. Turn the photo the right way up (phones often store a "rotate me"
         note instead of rotating the pixels)
      2. Shrink it to a tiny 9 × 8 grayscale picture. This throws away
         size, sharpness, file type and compression — exactly the things
         that differ between copies of the same photo
      3. In each row, check whether each spot is brighter than the spot to
         its right. 8 rows × 8 checks = 64 yes/no answers

    Copies of the same photo give (almost) the same 64 answers; different
    photos give very different ones.
    """
    try:
        with warnings.catch_warnings():
            # Pillow warns about very large pictures (like panoramas). They
            # are your own photos, so the warning isn't useful here.
            warnings.simplefilter("ignore")
            with Image.open(f.path) as img:
                width, height = img.size
                if img.getexif().get(ORIENTATION_TAG, 1) in (5, 6, 7, 8):
                    width, height = height, width  # stored sideways
                # For JPEG photos, ask Pillow to decode a small version
                # directly. Much faster for big phone photos.
                img.draft("L", (72, 64))
                upright = ImageOps.exif_transpose(img)
                tiny = flatten_to_gray(upright).resize((9, 8), Image.LANCZOS)
                pixels = tiny.tobytes()
    except Exception:
        # Damaged files, or formats Pillow can't read: just leave them out
        return None

    if max(pixels) - min(pixels) < MIN_PHOTO_DETAIL:
        return None

    bits = 0
    for row in range(8):
        for col in range(8):
            left, right = pixels[row * 9 + col], pixels[row * 9 + col + 1]
            bits = (bits << 1) | (left > right)
    return PhotoPrint(f, bits, width, height)


def differences(a: int, b: int) -> int:
    """How many of the 64 checks differ between two fingerprints."""
    return bin(a ^ b).count("1")


def same_shape(a: PhotoPrint, b: PhotoPrint) -> bool:
    """True if both photos have (nearly) the same width-to-height shape."""
    ratio_a, ratio_b = a.width / a.height, b.width / b.height
    return abs(ratio_a - ratio_b) <= SHAPE_TOLERANCE * max(ratio_a, ratio_b)


def fingerprint_pieces(bits: int, pieces: int) -> list[int]:
    """Cut a 64-check fingerprint into `pieces` roughly equal slices."""
    values = []
    for i in range(pieces):
        start, end = i * 64 // pieces, (i + 1) * 64 // pieces
        values.append((bits >> start) & ((1 << (end - start)) - 1))
    return values


def similarity_threshold() -> int:
    """The SIMILARITY_THRESHOLD setting, kept within a sensible range."""
    if 0 <= SIMILARITY_THRESHOLD <= MAX_SIMILARITY_THRESHOLD:
        return SIMILARITY_THRESHOLD
    value = max(0, min(SIMILARITY_THRESHOLD, MAX_SIMILARITY_THRESHOLD))
    print(f"⚠️  SIMILARITY_THRESHOLD must be between 0 and {MAX_SIMILARITY_THRESHOLD}. Using {value}.")
    return value


def find_similar_photos(
    photos: list[FileInfo], keep_key: Callable[[FileInfo], tuple]
) -> tuple[list[Group], int]:
    """
    Group photos that look the same. Returns (groups, photos that couldn't be compared).

    Each group is built around the photo with the most pixels (the sharpest
    version), and every other photo in the group must be similar to THAT
    photo. This stops a long burst of shots from chaining into one group.
    """
    threshold = similarity_threshold()
    print(f"Looking for similar photos among {plural(len(photos), 'picture')}...")

    prints: list[PhotoPrint] = []
    not_compared = 0
    for done, f in enumerate(photos, start=1):
        fingerprint = photo_fingerprint(f)
        if fingerprint is None:
            not_compared += 1
        else:
            prints.append(fingerprint)
        show_progress(done, len(photos), "Looked at", "pictures")
    print(f"   Looked at {len(photos):,} of {len(photos):,} pictures.")

    # Best version first: most pixels, then biggest file, then the KEEP rule
    prints.sort(key=lambda p: (-(p.width * p.height), -p.file.size, keep_key(p.file)))

    # Comparing every photo with every other photo gets slow (10,000 photos
    # would mean 50 million comparisons). The shortcut: cut each fingerprint
    # into (threshold + 1) slices. If two fingerprints differ in at most
    # `threshold` places, at least one slice must be exactly the same, so we
    # only compare photos that share a slice.
    pieces = threshold + 1
    shares_slice: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, p in enumerate(prints):
        for number, value in enumerate(fingerprint_pieces(p.bits, pieces)):
            shares_slice[(number, value)].append(index)

    taken = [False] * len(prints)
    groups: list[Group] = []
    for index, best in enumerate(prints):
        if taken[index]:
            continue
        taken[index] = True

        nearby: set[int] = set()
        for number, value in enumerate(fingerprint_pieces(best.bits, pieces)):
            nearby.update(shares_slice[(number, value)])

        extras = []
        for other in sorted(nearby):
            candidate = prints[other]
            if taken[other] or differences(best.bits, candidate.bits) > threshold:
                continue
            if same_shape(best, candidate):
                taken[other] = True
                extras.append(candidate.file)
        if extras:
            groups.append(Group("similar", best.file, extras))

    return groups, not_compared


# ---------------------------------------------------------------------------
# Step 4: report and summary
# ---------------------------------------------------------------------------

def shown_path(folder: Path, f: FileInfo) -> str:
    """How a file is written in the report, e.g. Downloads/Taxes/report.pdf."""
    return str(Path(folder.name) / f.rel)


def short(text: str, width: int = 55) -> str:
    """Shorten long paths for the terminal, keeping the end (the file name)."""
    return text if len(text) <= width else "…" + text[-(width - 1):]


def write_report(path: Path, folder: Path, groups: list[Group]) -> bool:
    """
    Save every group to a CSV file you can open in Excel, Numbers or Google
    Sheets. Returns False (after explaining) if it couldn't be saved.
    """
    try:
        # utf-8-sig makes Excel show accents like é correctly
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["group", "kept_file", "duplicate_file", "size", "size_bytes", "reason", "plan"]
            )
            for number, group in enumerate(groups, start=1):
                moving = group.reason == "exact" or MOVE_SIMILAR_PHOTOS
                plan = "move to review folder" if moving else "only listed - check by eye"
                for extra in group.extras:
                    writer.writerow([
                        number,
                        shown_path(folder, group.keep),
                        shown_path(folder, extra),
                        format_size(extra.size),
                        extra.size,
                        group.reason,
                        plan,
                    ])
    except OSError as err:
        print(f"⚠️  Couldn't save the report {path.name}: {err}")
        print("   If it is open in Excel or another program, close it and run the tool again.")
        print()
        return False
    return True


def show_summary(exact: list[Group], similar: list[Group], photo_note: str) -> None:
    """Print how many copies were found and the biggest groups."""
    print("What was found:")
    if exact:
        copies = sum(len(g.extras) for g in exact)
        size = format_size(sum(g.extra_size for g in exact))
        print(
            f"   Exact copies:    {plural(len(exact), 'group')}, "
            f"{plural(copies, 'extra copy', 'extra copies')}, {size}"
        )
    else:
        print("   Exact copies:    none")

    if photo_note:
        print(f"   Similar photos:  {photo_note}")
    elif similar:
        photos = sum(len(g.extras) for g in similar)
        size = format_size(sum(g.extra_size for g in similar))
        what = "will be moved too" if MOVE_SIMILAR_PHOTOS else "only listed in the report"
        print(
            f"   Similar photos:  {plural(len(similar), 'group')}, "
            f"{plural(photos, 'photo')}, {size} ({what})"
        )
    else:
        print("   Similar photos:  none")

    freeable = exact + (similar if MOVE_SIMILAR_PHOTOS else [])
    print(f"   Space you could free: {format_size(sum(g.extra_size for g in freeable))}")
    print()

    biggest = sorted(exact + similar, key=lambda g: -g.extra_size)[:TOP_GROUPS]
    if biggest:
        print("Biggest groups:")
        for number, group in enumerate(biggest, start=1):
            if group.reason == "exact":
                what = plural(len(group.extras), "extra copy", "extra copies")
            else:
                what = plural(len(group.extras), "similar photo")
            print(f"   {number}. {short(str(group.keep.rel))}  ({what}, {format_size(group.extra_size)})")
        print()


# ---------------------------------------------------------------------------
# Step 5: move the extra copies (and the undo log)
# ---------------------------------------------------------------------------

def free_destination(target: Path, claimed: set[str]) -> Path:
    """
    Return `target`, or "name (2).ext", "name (3).ext"... if that spot is
    already used — by a file from an earlier run, or by another file in this
    run. Names are compared ignoring capital letters, because Mac and
    Windows treat "Photo.JPG" and "photo.jpg" as the same file.
    """
    candidate = target
    number = 2
    while candidate.exists() or candidate.is_symlink() or str(candidate).casefold() in claimed:
        candidate = target.with_name(f"{target.stem} ({number}){target.suffix}")
        number += 1
    claimed.add(str(candidate).casefold())
    return candidate


def plan_moves(folder: Path, review: Path, groups: list[Group]) -> list[Move]:
    """Work out where in the review folder each extra copy goes."""
    claimed: set[str] = set()
    moves = []
    for group in groups:
        for extra in group.extras:
            target = review / folder.name / extra.rel
            moves.append(Move(extra, group.keep, free_destination(target, claimed), group.reason))
    return moves


def show_preview(moves: list[Move]) -> None:
    """Print the first few files that will be moved and what they copy."""
    for move in moves[:PREVIEW_LINES]:
        twin = "same as" if move.reason == "exact" else "looks like"
        print(f"   {short(str(move.source.rel), 40)}  ({twin} {short(str(move.keep.rel), 35)})")
    if len(moves) > PREVIEW_LINES:
        print(f"   ... and {len(moves) - PREVIEW_LINES:,} more")
    print()


def log_path(path: Path, base: Path) -> str:
    """A path for the undo log: relative to `base`, with "/" between folders."""
    return path.relative_to(base).as_posix()


def from_log_path(text: str, base: Path) -> Path:
    """Turn a path from the undo log back into a real path, refusing odd ones."""
    parts = text.split("/")
    if not text or text.startswith("/") or PureWindowsPath(text).drive or ".." in parts:
        raise ValueError(f"the undo log '{UNDO_LOG_NAME}' looks damaged")
    return base.joinpath(*parts)


def read_undo_log(review: Path) -> list[LogRow]:
    """Load the undo log, or return an empty list if there isn't one."""
    path = review / UNDO_LOG_NAME
    if not path.exists():
        return []

    rows: list[LogRow] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for line in csv.DictReader(f):
            try:
                rows.append(LogRow(int(line["run"]), line["original"], line["review_copy"]))
            except (KeyError, TypeError, ValueError) as err:
                raise ValueError(f"the undo log '{UNDO_LOG_NAME}' looks damaged") from err
    return rows


def write_undo_log(review: Path, rows: list[LogRow]) -> None:
    """Save the undo log (or remove it when empty), never leaving it half-written."""
    path = review / UNDO_LOG_NAME
    if not rows:
        if path.exists():
            path.unlink()
        return
    temp_path = review / (UNDO_LOG_NAME + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "original", "review_copy"])
        for row in rows:
            writer.writerow([row.run, row.original, row.review_copy])
    os.replace(temp_path, path)


def move_file(source: Path, target: Path) -> None:
    """Move one file, refusing to overwrite anything that is already there."""
    # On Mac and Linux a plain move silently REPLACES an existing file,
    # so we always check first.
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"'{target}' already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    # os.rename only moves within the same drive, so the file is never
    # copied and deleted — it simply gets a new place, instantly.
    os.rename(source, target)


def changed_since_scan(move: Move) -> Optional[str]:
    """
    Last check right before moving: the extra copy must be exactly as we
    scanned it, and its twin that stays must still be there. Otherwise you
    could end up with no copy left in place.
    """
    try:
        info = os.lstat(move.source.path)
    except OSError:
        return "it is no longer there"
    if info.st_size != move.source.size or info.st_mtime_ns != move.source.mtime_ns:
        return "it changed after the check"
    if not move.keep.path.is_file():
        return f"the copy that should stay ({move.keep.rel}) is gone"
    return None


def remove_empty_folders(review: Path) -> None:
    """Tidy up: remove EMPTY folders inside the review folder (never any file)."""
    if not review.is_dir():
        return
    for current, _folders, _files in os.walk(review, topdown=False):
        try:
            os.rmdir(current)  # Only works when the folder is empty
        except OSError:
            pass


def move_duplicates(moves: list[Move], review: Path) -> tuple[int, int, list[str]]:
    """
    Move every extra copy into the review folder.
    Returns (files moved, bytes moved, problems).

    The undo log is saved BEFORE anything moves, so it exists even if the
    computer stops halfway. Afterwards it is updated to list exactly the
    files that really moved. A file that can't be moved (for example because
    it is open in another program) is skipped and the rest carry on.
    """
    base = review.parent
    if not review.exists():
        review.mkdir(parents=True)
        print(f"📁 Created folder: {review}")

    earlier = read_undo_log(review)
    run = earlier[-1].run + 1 if earlier else 1
    planned = [
        LogRow(run, log_path(m.source.path, base), log_path(m.destination, base)) for m in moves
    ]
    write_undo_log(review, earlier + planned)

    moved: list[LogRow] = []
    moved_bytes = 0
    problems: list[str] = []
    total = len(moves)
    print("Moving...")
    try:
        for count, (move, row) in enumerate(zip(moves, planned), start=1):
            problem = changed_since_scan(move)
            if problem is None:
                try:
                    move_file(move.source.path, move.destination)
                except OSError as err:
                    problem = str(err)
            if problem:
                problems.append(f"{move.source.rel}: {problem}")
            else:
                moved.append(row)
                moved_bytes += move.source.size
            show_progress(count, total, "Moved", "files")
    except KeyboardInterrupt:
        write_undo_log(review, earlier + moved)
        print()
        print(f"Stopped. {plural(len(moved), 'file')} had already been moved; nothing was deleted.")
        print("They are listed in the undo log, so  --undo  can put them back.")
        raise SystemExit(1) from None

    if len(moved) != total:
        write_undo_log(review, earlier + moved)
        remove_empty_folders(review)
    print(f"   Moved {len(moved):,} of {total:,} file(s).")
    print()
    return len(moved), moved_bytes, problems


# ---------------------------------------------------------------------------
# The two modes: find duplicates, and undo
# ---------------------------------------------------------------------------

def remember_review_folder(review: Path) -> None:
    """Save the LAST_RUN_NOTE, so a plain --undo knows where to look."""
    try:
        (Path(".") / LAST_RUN_NOTE).write_text(str(review), encoding="utf-8")
    except OSError:
        pass  # Only a convenience: the full undo command is printed anyway


def remembered_review_folder() -> Optional[Path]:
    """The review folder from the last run, if it still has an undo log."""
    try:
        text = (Path(".") / LAST_RUN_NOTE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    review = Path(text)
    return review if text and (review / UNDO_LOG_NAME).is_file() else None


def review_folder_for_undo(folder: Path, is_default: bool) -> Path:
    """
    Work out which review folder --undo should empty.
      - With a folder typed: the review folder next to it (or that folder
        itself, if you typed the path of the review folder)
      - Without: the one used last time, or else the project's own
    """
    if is_default:
        remembered = remembered_review_folder()
        if remembered is not None:
            print(f"📁 Using the review folder from the last time files were moved: {remembered}")
            print()
            return remembered
        return (Path(".") / REVIEW_FOLDER_NAME).resolve()
    folder = folder.resolve()
    return folder if folder.name == REVIEW_FOLDER_NAME else folder.parent / REVIEW_FOLDER_NAME


def undo_command(folder: Path, is_default: bool) -> str:
    """The exact command to type to undo, quoted for paths with spaces."""
    if is_default:
        return "python duplicate_finder.py --undo"
    return f'python duplicate_finder.py --undo "{folder}"'


def find_duplicates(folder: Path, is_default: bool) -> None:
    """The normal mode: scan, report, preview, confirm, move."""
    folder = folder.resolve()
    review = folder.parent / REVIEW_FOLDER_NAME
    report = Path(".").resolve() / REPORT_NAME
    rule = keep_rule()
    keep_key = keep_order(rule)

    print("Listing files...")
    scan = scan_folder(folder)
    total_size = sum(f.size for f in scan.files)
    print(f"   Found {plural(len(scan.files), 'file')} to check ({format_size(total_size)}).")
    if scan.skipped:
        print(f"   (Skipped {plural(scan.skipped, 'hidden, empty, system or shortcut file')}.)")
    print()

    if not scan.files:
        print("No files found to check yet.")
        print()
        print("What to do next:")
        if is_default:
            print(f"  1. Open the folder named '{FOLDER_NAME}'.")
            print("  2. Copy or move the files you want to check into it (sub-folders are fine).")
            print("  3. Run this script again:")
            print()
            print("         python duplicate_finder.py")
            print()
            print("Or check another folder directly, for example:")
            print()
            print("         python duplicate_finder.py ~/Downloads")
        else:
            print("  Hidden files, empty files and shortcuts are skipped.")
            print("  Check that this is the right folder, or choose another one.")
        print()
        return

    sets, unreadable = find_exact_copies(scan.files)
    unreadable += scan.unreadable
    exact = []
    for files in sets:
        ordered = sorted(files, key=keep_key)
        exact.append(Group("exact", ordered[0], ordered[1:]))
    exact.sort(key=lambda g: (-g.extra_size, str(g.keep.rel).casefold()))

    # Only one file per set of exact copies needs comparing for similarity:
    # the one that stays. Its extra copies are already being handled.
    extra_copies = {f.path for g in exact for f in g.extras}
    remaining = [f for f in scan.files if f.path not in extra_copies]
    photos = [f for f in remaining if f.path.suffix.lower() in PHOTO_EXTENSIONS]

    similar: list[Group] = []
    photo_note = ""
    if not CHECK_SIMILAR_PHOTOS:
        photo_note = "not checked (CHECK_SIMILAR_PHOTOS is turned off)"
    elif Image is None:
        photo_note = "not checked (install Pillow to turn this on: pip install Pillow)"
    elif len(photos) > 1:
        similar, not_compared = find_similar_photos(photos, keep_key)
        similar.sort(key=lambda g: (-g.extra_size, str(g.keep.rel).casefold()))
        if not_compared:
            print(f"   ({plural(not_compared, 'picture')} couldn't be compared: unreadable or almost blank.)")
        print()

    if unreadable:
        print(f"⚠️  {plural(unreadable, 'file or folder', 'files or folders')} couldn't be opened and were skipped")
        print("   (no permission, or open in another program).")
        print()

    show_summary(exact, similar, photo_note)

    groups = exact + similar
    if not groups:
        print("=" * 60)
        print("All done! No duplicates found — nothing to tidy up here.")
        print("=" * 60)
        print()
        return

    if write_report(report, folder, groups):
        print(f"Full list saved to: {report}")
        print("   (Open it in Excel, Numbers or Google Sheets.)")
        print()

    to_move = exact + (similar if MOVE_SIMILAR_PHOTOS else [])
    moves = plan_moves(folder, review, to_move)
    if not moves:
        print("=" * 60)
        print("All done! There are no exact copies to move.")
        print("The similar photos are only listed in the report — check them by eye.")
        print("=" * 60)
        print()
        return

    move_size = format_size(sum(m.source.size for m in moves))
    kept = {
        "oldest": "the oldest file of each set",
        "newest": "the newest file of each set",
        "shortest_path": "the file with the shortest path in each set",
    }[rule]
    print(f"Here is what will happen (keeping {kept} where it is):")
    show_preview(moves)
    print(f"The extra copies go into: {review}")
    print("   (Their folder layout is kept, so nothing gets mixed up. Nothing is deleted.)")
    print()

    copies = plural(len(moves), "duplicate copy", "duplicate copies")
    if not ask_yes(f"Move {copies} ({move_size}) to the review folder? Type y to continue: "):
        print()
        print("Cancelled — nothing was moved.")
        return
    print()

    moved, moved_bytes, problems = move_duplicates(moves, review)
    if moved:
        remember_review_folder(review)

    if problems:
        print(f"⚠️  {plural(len(problems), 'file was', 'files were')} left where they were:")
        for problem in problems[:PREVIEW_LINES]:
            print(f"   {problem}")
        if len(problems) > PREVIEW_LINES:
            print(f"   ... and {len(problems) - PREVIEW_LINES:,} more")
        print()

    print("=" * 60)
    print(f"All done! Moved {plural(moved, 'duplicate copy', 'duplicate copies')} ({format_size(moved_bytes)}) to:")
    print(f"   {review}")
    print()
    print("Nothing was deleted. What to do next:")
    print("  1. Open the review folder and look through the files.")
    print("  2. When you're happy, delete the review folder yourself to free the space.")
    print()
    print("Changed your mind? Put every file back with:")
    print()
    print(f"    {undo_command(folder, is_default)}")
    print("=" * 60)
    print()


def undo_moves(review: Path) -> None:
    """The --undo mode: move every file from the review folder back."""
    base = review.parent

    rows = read_undo_log(review)
    if not rows:
        print(f"Nothing to undo — there is no undo log in {review}")
        print("(An undo log is saved each time this tool moves files.)")
        print()
        return

    plan: list[tuple[LogRow, Path, Path]] = []
    missing: list[str] = []
    for row in rows:
        copy, original = from_log_path(row.review_copy, base), from_log_path(row.original, base)
        if copy.is_file() and not copy.is_symlink():
            plan.append((row, copy, original))
        elif not original.exists():
            missing.append(row.review_copy)
        # Otherwise it is already back where it was: nothing to do

    if missing:
        print(f"⚠️  {plural(len(missing), 'moved file is', 'moved files are')} no longer in the review folder (deleted?):")
        for name in missing[:PREVIEW_LINES]:
            print(f"   {name}")
        if len(missing) > PREVIEW_LINES:
            print(f"   ... and {len(missing) - PREVIEW_LINES:,} more")
        print("   These can't be put back and will be skipped.")
        print()

    if not plan:
        write_undo_log(review, [])
        remove_empty_folders(review)
        print("Nothing to undo — no moved files were found. The undo log was removed.")
        print()
        return

    # Check EVERY original spot is free before moving anything back
    problems: list[str] = []
    claimed: dict[str, str] = {}
    for row, _copy, original in plan:
        key = str(original).casefold()
        if original.exists() or original.is_symlink():
            problems.append(f"'{row.original}' is taken by another file now.")
        elif key in claimed:
            problems.append(f"'{claimed[key]}' and '{row.review_copy}' both came from '{row.original}'.")
        claimed[key] = row.review_copy
    if problems:
        print("⚠️  Stopped before changing anything, because some original spots are taken:")
        for problem in problems[:PREVIEW_LINES]:
            print(f"   {problem}")
        if len(problems) > PREVIEW_LINES:
            print(f"   ... and {len(problems) - PREVIEW_LINES:,} more")
        print()
        print("Move or rename those files (they may be newer copies you want to keep),")
        print("then run the undo command again.")
        print()
        return

    print("Here is what will happen:")
    for row, _copy, _original in plan[:PREVIEW_LINES]:
        print(f"   {short(row.original, 70)}")
    if len(plan) > PREVIEW_LINES:
        print(f"   ... and {len(plan) - PREVIEW_LINES:,} more")
    print()

    if not ask_yes(f"Put back {plural(len(plan), 'file')} from the review folder? Type y to continue: "):
        print()
        print("Cancelled — nothing was moved.")
        return
    print()

    print("Putting files back...")
    left_over: list[LogRow] = []
    failures: list[str] = []
    try:
        for count, (row, copy, original) in enumerate(plan, start=1):
            try:
                move_file(copy, original)
            except OSError as err:
                left_over.append(row)
                failures.append(f"{row.original}: {err}")
            show_progress(count, len(plan), "Put back", "files")
    except KeyboardInterrupt:
        done = {row for row, _c, original in plan if original.exists()}
        write_undo_log(review, [row for row, _c, _o in plan if row not in done])
        print()
        print("Stopped. Run the undo command again to put back the rest.")
        raise SystemExit(1) from None

    # The log now only lists files that are still in the review folder
    write_undo_log(review, left_over)
    remove_empty_folders(review)
    note = Path(".") / LAST_RUN_NOTE
    if not left_over and remembered_review_folder() is None and note.exists():
        note.unlink()  # Its review folder has nothing left to undo
    restored = len(plan) - len(left_over)
    print(f"   Put back {restored:,} of {len(plan):,} file(s).")
    print()

    if failures:
        print(f"⚠️  {plural(len(failures), 'file')} couldn't be put back:")
        for failure in failures[:PREVIEW_LINES]:
            print(f"   {failure}")
        print("   Close them in any other program and run the undo command again.")
        print()

    print("=" * 60)
    print(f"All done! {plural(restored, 'file')} {'is' if restored == 1 else 'are'} back where they were.")
    if review.exists():
        print(f"(The review folder still holds other files, so it was left in place: {review})")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main program — runs when you type: python duplicate_finder.py
# ---------------------------------------------------------------------------

def show_usage() -> None:
    print("Use one of these:")
    print("    python duplicate_finder.py                    (check the files_to_check folder)")
    print("    python duplicate_finder.py ~/Downloads        (check another folder)")
    print("    python duplicate_finder.py --undo             (put moved files back)")
    print('    python duplicate_finder.py --undo "<folder>"  (undo for another folder)')
    print()


def main(argv: Optional[list[str]] = None) -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    args = sys.argv[1:] if argv is None else argv
    undo = "--undo" in args
    options = [a for a in args if a.startswith("-") and a != "--undo"]
    words = [a for a in args if not a.startswith("-")]

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Duplicate File Finder" + (" (undo)" if undo else ""))
    print("=" * 60)
    print()

    if options:
        if options not in (["--help"], ["-h"]):
            print(f"Unknown option: {' '.join(options)}")
            print()
        show_usage()
        raise SystemExit(0 if options in (["--help"], ["-h"]) else 2)

    is_default = not words
    folder = Path(".") / FOLDER_NAME if is_default else clean_typed_path(" ".join(words))

    if not undo:
        # Safety first: refuse dangerous folders before looking at anything
        problem = safety_problem(folder)
        if problem:
            print(f"⚠️  {problem}")
            print()
            raise SystemExit(1)
        found = ensure_folder() if is_default else folder_from_arguments(words)
        if found is None:
            raise SystemExit(1)
        folder = found

    try:
        if undo:
            undo_moves(review_folder_for_undo(folder, is_default))
        else:
            find_duplicates(folder, is_default)
    except KeyboardInterrupt:
        print()
        print("Stopped. Nothing was moved.")
        raise SystemExit(1)
    except (OSError, ValueError) as err:
        print()
        print(f"⚠️  Something went wrong: {err}")
        print("Nothing was deleted. Any files already moved are listed in the undo log.")
        print("If a file is open in another program, close it and try again.")
        print()
        raise SystemExit(1)


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

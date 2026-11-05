#!/usr/bin/env python3
"""
Bulk File Renamer
=================
This script gives every file in a "files_to_rename" folder a tidy, numbered
name that you choose, for example:

    DCIM_00412.jpg  →  Project_Photos_001.jpg
    DCIM_00413.jpg  →  Project_Photos_002.jpg

Unlike the other tools in this hub, it renames your files IN PLACE instead of
making copies, because copying hundreds of photos would double the space they
take up. To keep that safe, it:

  1. Shows you a preview and only renames after you type y
  2. Never overwrites a file. If a new name is already taken, it stops
     before changing anything
  3. Saves an "undo log" so you can put every old name back later

How to run (after following README.md):
    python bulk_renamer.py

To put every old name back:
    python bulk_renamer.py --undo
"""

# ---------------------------------------------------------------------------
# Imports — all built into Python, nothing extra to install
# ---------------------------------------------------------------------------

import csv  # Reads and writes the undo log (a small spreadsheet-style file)
import os  # Low-level "rename this file" command
import re  # "Regular expressions": used to find the numbers inside file names
import sys  # Gives access to the terminal output settings and the --undo option
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the files to rename. They are renamed right here.
FOLDER_NAME = "files_to_rename"

# How to decide which file becomes number 1, 2, 3 ...
#   "name" — by file name, reading numbers the way a person would, so
#            DCIM_2 comes before DCIM_10. Best when all files come from one
#            camera or phone, because their names are already in shooting order.
#   "date" — oldest "last modified" date first. Best when files come from
#            several devices that name files differently. Copying or
#            downloading files can reset this date, so check the preview.
SORT_BY = "name"

# The first number to use (1 gives _001, _002, ...)
START_NUMBER = 1

# Numbers are padded with zeros to at least this many digits (001, 002, ...)
# so the files stay in the right order in every file browser. With 1000 or
# more files we automatically use more digits (0001 ... 1000).
MIN_DIGITS = 3

# What goes between your base name and the number: Project_Photos_001
SEPARATOR = "_"

# How many "old → new" lines to show in the preview before asking
PREVIEW_LINES = 10

# For big batches, print a progress line after every this many files
PROGRESS_EVERY = 50

# The undo log lives inside the folder. The dot at the start hides it on
# Mac and Linux, and it also means this tool never tries to rename it.
UNDO_LOG_NAME = ".rename_undo_log.csv"

# While renaming, each file briefly gets this ending added to its name
# (see rename_in_two_phases below). You should never normally see it.
TEMP_SUFFIX = ".bulk_renamer_tmp"

# Very long names can break on Windows, which limits the length of a full path
MAX_BASE_NAME_LENGTH = 100

# Windows does not allow these characters in file names. We block them on
# every computer so the renamed files can still be copied to a Windows PC.
INVALID_CHARACTERS = '\\/:*?"<>|'

# Windows creates these helper files by itself — they should keep their names
SYSTEM_FILES = {"thumbs.db", "desktop.ini"}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class Rename(NamedTuple):
    """One planned change: the file's current name and the name it will get."""

    old: str
    new: str


class LogRow(NamedTuple):
    """One line of the undo log. "run" counts how many times the tool was used."""

    run: int
    old: str
    new: str


def ensure_folder() -> Path:
    """Make sure the files_to_rename folder exists and return its path."""
    # Path(".") means "the folder where you ran the script from"
    folder = Path(".") / FOLDER_NAME

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {folder.resolve()}")
        print("   → Put the files you want to rename in this folder, then run the script again.")
    else:
        print(f"📁 Found folder: {folder.resolve()}")
    print()

    return folder


def is_file_to_rename(item: Path) -> bool:
    """True for normal files we should number; False for everything we leave alone."""
    name = item.name
    # Hidden files (like .DS_Store on a Mac) and our own undo log start with "."
    if name.startswith("."):
        return False
    if name.lower() in SYSTEM_FILES:
        return False
    if name.endswith(TEMP_SUFFIX):
        return False
    # Sub-folders (and anything inside them) are never touched
    return item.is_file()


def natural_sort_key(name: str) -> tuple:
    """
    Sort names the way a person would: DCIM_2 before DCIM_10.

    A plain computer sort compares letter by letter, so "1" in "10" beats "2"
    and DCIM_10 lands before DCIM_2. Here we cut the name into text and number
    pieces ("dcim_", 10, ".jpg") and compare the numbers as real numbers.
    """
    parts = re.split(r"(\d+)", name.casefold())
    # The split always alternates text, number, text, number ... so every
    # odd position holds digits and can safely become a real number.
    pieces = tuple(int(part) if i % 2 else part for i, part in enumerate(parts))
    # The exact name breaks ties (e.g. "a01" and "a1") so the order never wobbles
    return pieces, name


def find_files(folder: Path) -> list[Path]:
    """Return the files to rename, sorted the way SORT_BY asks."""
    files = [item for item in folder.iterdir() if is_file_to_rename(item)]

    if SORT_BY == "date":
        return sorted(files, key=lambda p: (p.stat().st_mtime, natural_sort_key(p.name)))
    if SORT_BY != "name":
        print(f"⚠️  SORT_BY is set to '{SORT_BY}', which isn't 'name' or 'date'. Sorting by name.")
        print()
    return sorted(files, key=lambda p: natural_sort_key(p.name))


def clean_base_name(raw: str) -> tuple[str, Optional[str]]:
    """
    Tidy up the base name the user typed and check it is safe to use.

    Returns (cleaned_name, problem). "problem" is None when the name is fine,
    otherwise a friendly sentence explaining what to change.
    """
    name = raw.strip()

    # Spaces inside file names turn into "%20" in web links and cause trouble
    # in some upload forms and terminals, so "Project Photos" becomes
    # "Project_Photos". Underscores keep the words easy to read.
    name = re.sub(r"\s+", "_", name)

    if not name:
        return name, "The name can't be empty. Please type something like Project_Photos."

    bad = sorted({c for c in name if c in INVALID_CHARACTERS or ord(c) < 32})
    if bad:
        shown = " ".join(c if ord(c) >= 32 else "(invisible character)" for c in bad)
        return name, f"File names can't contain these characters: {shown}  Please leave them out."

    if name.startswith("."):
        return name, "The name can't start with a dot — that would hide your files on Mac and Linux."

    if name.endswith("."):
        return name, "The name can't end with a dot — Windows quietly removes it, which causes confusion."

    if len(name) > MAX_BASE_NAME_LENGTH:
        return name, f"That name is too long. Please keep it under {MAX_BASE_NAME_LENGTH} characters."

    return name, None


def ask_for_base_name() -> Optional[str]:
    """Keep asking until we get a usable base name. Returns None if input ends."""
    while True:
        try:
            answer = input("Type the new base name (for example Project_Photos): ")
        except EOFError:
            # Nothing more can be typed (e.g. the input was piped in and ran out)
            return None

        name, problem = clean_base_name(answer)
        if problem:
            print(f"   ⚠️  {problem}")
            continue

        if name != answer.strip():
            print(f"   Using: {name}")
        return name


def ask_yes(question: str) -> bool:
    """Ask a yes/no question. Only "y" or "yes" counts as yes."""
    try:
        answer = input(question)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def build_plan(files: list[Path], base_name: str) -> tuple[list[Rename], int]:
    """
    Work out the new name for every file.

    Returns (renames, how_many_already_had_the_right_name).
    """
    last_number = START_NUMBER + len(files) - 1
    # 9 files → 001 ... 009, 1000 files → 0001 ... 1000
    digits = max(MIN_DIGITS, len(str(last_number)))

    plan: list[Rename] = []
    unchanged = 0
    for number, path in enumerate(files, start=START_NUMBER):
        # The extension (.jpg, .PDF, ...) is kept exactly as it was, capital
        # letters included. Changing .JPG to .jpg could break links or
        # programs that expect the exact name, and gains nothing.
        new_name = f"{base_name}{SEPARATOR}{number:0{digits}d}{path.suffix}"
        if new_name == path.name:
            unchanged += 1
        else:
            plan.append(Rename(path.name, new_name))

    return plan, unchanged


def find_clashes(folder: Path, plan: list[Rename]) -> list[str]:
    """
    Check every new name is free before we change anything.

    A new name may reuse the name of a file that is itself being renamed
    (the two-phase rename makes that safe), but it must not match anything
    else in the folder, such as a sub-folder.

    Mac and Windows treat "Photo.JPG" and "photo.jpg" as the SAME name, so we
    compare names ignoring capital letters. On Linux that is extra cautious,
    which is fine.
    """
    moving = {r.old for r in plan}
    staying = {
        item.name.casefold(): item.name for item in folder.iterdir() if item.name not in moving
    }

    problems: list[str] = []
    claimed: dict[str, str] = {}
    for r in plan:
        key = r.new.casefold()
        if key in staying:
            problems.append(f"'{r.new}' already exists ('{staying[key]}') and isn't being renamed.")
        elif key in claimed:
            problems.append(f"'{claimed[key]}' and '{r.old}' would both be called '{r.new}'.")
        claimed[key] = r.old
    return problems


def show_preview(plan: list[Rename]) -> None:
    """Print the first few "old → new" lines so the user can check them."""
    shown = plan[:PREVIEW_LINES]
    width = min(40, max(len(r.old) for r in shown))
    for r in shown:
        print(f"   {r.old:<{width}}  →  {r.new}")
    if len(plan) > len(shown):
        print(f"   ... and {len(plan) - len(shown)} more")
    print()


def move_file(folder: Path, old_name: str, new_name: str) -> None:
    """Rename one file, refusing to overwrite anything that is already there."""
    target = folder / new_name
    # On Mac and Linux a plain rename silently REPLACES an existing file,
    # so we always check first.
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"'{new_name}' already exists")
    os.rename(folder / old_name, target)


def put_names_back(folder: Path, completed: list[tuple[str, str]]) -> None:
    """Undo the renames done so far, newest first, after something went wrong."""
    for old_name, new_name in reversed(completed):
        try:
            move_file(folder, new_name, old_name)
        except OSError as err:
            print(f"   ⚠️  Could not put back '{old_name}' (it is now called '{new_name}'): {err}")


def rename_in_two_phases(folder: Path, plan: list[Rename]) -> None:
    """
    Rename every file without ever overwriting one.

    Renaming straight from old to new can fail when names overlap. For
    example, if file A should become "Photo_002" but another file still has
    that name. So:
      Phase 1: give every file a temporary name nobody else is using
      Phase 2: give each file its final name — by now all those names are free

    If ANY rename fails (for example a file is open in another program),
    every file done so far is put back, so you never end up half-renamed.
    """
    completed: list[tuple[str, str]] = []
    total = len(plan)

    try:
        for r in plan:
            temp_name = r.old + TEMP_SUFFIX
            move_file(folder, r.old, temp_name)
            completed.append((r.old, temp_name))

        for count, r in enumerate(plan, start=1):
            temp_name = r.old + TEMP_SUFFIX
            move_file(folder, temp_name, r.new)
            completed.append((temp_name, r.new))
            if count % PROGRESS_EVERY == 0 and count < total:
                print(f"   Renamed {count} of {total} files...")
    except BaseException:
        # BaseException also catches Ctrl+C, so stopping early is safe too
        put_names_back(folder, completed)
        raise

    print(f"   Renamed {total} of {total} file(s).")


def read_undo_log(folder: Path) -> list[LogRow]:
    """Load the undo log, or return an empty list if there isn't one."""
    log_path = folder / UNDO_LOG_NAME
    if not log_path.exists():
        return []

    rows: list[LogRow] = []
    # utf-8-sig matches how we save it, so Excel shows accents like é correctly
    with log_path.open(newline="", encoding="utf-8-sig") as f:
        for line in csv.DictReader(f):
            try:
                rows.append(LogRow(int(line["run"]), line["old_name"], line["new_name"]))
            except (KeyError, TypeError, ValueError) as err:
                raise ValueError(f"the undo log '{UNDO_LOG_NAME}' looks damaged") from err
    return rows


def write_undo_log(folder: Path, rows: list[LogRow]) -> None:
    """Save the undo log, writing a temporary copy first so it is never half-written."""
    log_path = folder / UNDO_LOG_NAME
    temp_path = folder / (UNDO_LOG_NAME + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "old_name", "new_name"])
        for row in rows:
            writer.writerow([row.run, row.old, row.new])
    os.replace(temp_path, log_path)


def original_names(rows: list[LogRow]) -> dict[str, str]:
    """
    Work out each file's very first name from the whole undo log.

    If you renamed twice (DCIM_1.jpg → Trip_001.jpg → Beach_001.jpg), the log
    has one line per run. We replay the runs in order, keeping track of
    "current name → original name", so --undo goes all the way back.
    """
    current_to_original: dict[str, str] = {}
    runs: dict[int, list[LogRow]] = {}
    for row in rows:
        runs.setdefault(row.run, []).append(row)

    for run_rows in runs.values():
        # Within one run all files moved at the same time, so look up every
        # old name first and only then record the new names (handles swaps).
        moved = {row.new: current_to_original.pop(row.old, row.old) for row in run_rows}
        current_to_original.update(moved)

    return {current: original for current, original in current_to_original.items() if current != original}


def found_interrupted_run(folder: Path) -> bool:
    """
    Spot files left with a temporary name by a run that was cut off (for
    example by a power cut). Rather than guess, we stop and explain.
    """
    leftovers = sorted(p.name for p in folder.iterdir() if p.name.endswith(TEMP_SUFFIX))
    if not leftovers:
        return False

    print(f"⚠️  Found {len(leftovers)} file(s) with a temporary name ending in '{TEMP_SUFFIX}':")
    for name in leftovers[:PREVIEW_LINES]:
        print(f"   {name}")
    if len(leftovers) > PREVIEW_LINES:
        print(f"   ... and {len(leftovers) - PREVIEW_LINES} more")
    print()
    print("This means an earlier rename was interrupted before it finished.")
    print("To be safe, nothing will be changed until this is sorted out:")
    print(f"  1. Each file's earlier name is its name without '{TEMP_SUFFIX}'.")
    print(f"  2. The file '{UNDO_LOG_NAME}' in the folder lists old and new names.")
    print("  3. Rename those files by hand, then run this script again.")
    print()
    return True


def rename_files(folder: Path) -> None:
    """The normal mode: ask for a base name, preview, confirm, rename."""
    files = find_files(folder)

    if not files:
        print("No files found to rename yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{FOLDER_NAME}'.")
        print("  2. Copy or move the files you want to rename into it.")
        print("     (Files are renamed in place — keep a backup of anything important.)")
        print("  3. Run this script again:")
        print()
        print("         python bulk_renamer.py")
        print()
        return

    order = "date (oldest first)" if SORT_BY == "date" else "name"
    print(f"Found {len(files)} file(s). They will be numbered in order of {order}.")
    print()

    base_name = ask_for_base_name()
    if base_name is None:
        print()
        print("Cancelled — nothing was renamed.")
        return
    print()

    plan, unchanged = build_plan(files, base_name)

    if not plan:
        print(f"Nothing to do — all {unchanged} file(s) already have these names.")
        print()
        return

    problems = find_clashes(folder, plan)
    if problems:
        print("⚠️  Stopped before changing anything, because some new names are taken:")
        for problem in problems[:PREVIEW_LINES]:
            print(f"   {problem}")
        print()
        print("Move or rename those items, or choose a different base name, then try again.")
        print()
        return

    print("Here is what will happen:")
    show_preview(plan)
    if unchanged:
        print(f"({unchanged} file(s) already have the right name and will be left alone.)")
        print()

    if not ask_yes(f"Rename these {len(plan)} files? Type y to continue: "):
        print()
        print("Cancelled — nothing was renamed.")
        return
    print()

    # Save the undo information BEFORE renaming, so it exists even if the
    # computer stops halfway. Earlier runs are kept, so --undo can always go
    # back to the very first names.
    log_path = folder / UNDO_LOG_NAME
    previous_log = log_path.read_bytes() if log_path.exists() else None
    rows = read_undo_log(folder)
    run = rows[-1].run + 1 if rows else 1
    write_undo_log(folder, rows + [LogRow(run, r.old, r.new) for r in plan])

    print("Renaming...")
    try:
        rename_in_two_phases(folder, plan)
    except BaseException:
        # Every name was put back, so the log goes back to how it was too
        if previous_log is None:
            log_path.unlink()
        else:
            log_path.write_bytes(previous_log)
        raise
    print()

    print("=" * 60)
    print(f"All done! Renamed {len(plan)} file(s) in the '{FOLDER_NAME}' folder.")
    print()
    print("Changed your mind? Put every old name back with:")
    print()
    print("    python bulk_renamer.py --undo")
    print("=" * 60)
    print()


def undo_renames(folder: Path) -> None:
    """The --undo mode: give every file its original name back."""
    rows = read_undo_log(folder)
    if not rows:
        print("Nothing to undo — there is no undo log in this folder yet.")
        print("(An undo log is saved each time this tool renames files.)")
        print()
        return

    plan: list[Rename] = []
    missing: list[str] = []
    for current, original in original_names(rows).items():
        if (folder / current).is_file():
            plan.append(Rename(current, original))
        else:
            missing.append(current)
    plan.sort(key=lambda r: natural_sort_key(r.new))

    if missing:
        print(f"⚠️  {len(missing)} renamed file(s) are no longer in the folder (moved or deleted?):")
        for name in missing[:PREVIEW_LINES]:
            print(f"   {name}")
        if len(missing) > PREVIEW_LINES:
            print(f"   ... and {len(missing) - PREVIEW_LINES} more")
        print("   These will be skipped.")
        print()

    if not plan:
        (folder / UNDO_LOG_NAME).unlink()
        print("Nothing to undo — no renamed files were found. The undo log was removed.")
        print()
        return

    problems = find_clashes(folder, plan)
    if problems:
        print("⚠️  Stopped before changing anything, because some original names are taken:")
        for problem in problems[:PREVIEW_LINES]:
            print(f"   {problem}")
        print()
        print("Move or rename those items, then run  python bulk_renamer.py --undo  again.")
        print()
        return

    print("Here is what will happen:")
    show_preview(plan)

    if not ask_yes(f"Put back the original names of these {len(plan)} files? Type y to continue: "):
        print()
        print("Cancelled — nothing was renamed.")
        return
    print()

    print("Putting the original names back...")
    rename_in_two_phases(folder, plan)
    # The log has done its job; removing it means a future undo starts fresh
    (folder / UNDO_LOG_NAME).unlink()
    print()

    print("=" * 60)
    print(f"All done! {len(plan)} file(s) have their original names back.")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main program — runs when you type: python bulk_renamer.py
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    args = sys.argv[1:] if argv is None else argv
    undo = args == ["--undo"]

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Bulk File Renamer" + (" (undo)" if undo else ""))
    print("=" * 60)
    print()

    if args and not undo:
        print(f"Unknown option: {' '.join(args)}")
        print()
        print("Use one of these:")
        print("    python bulk_renamer.py          (rename files)")
        print("    python bulk_renamer.py --undo   (put the old names back)")
        print()
        raise SystemExit(2)

    folder = ensure_folder()
    if found_interrupted_run(folder):
        raise SystemExit(1)

    try:
        if undo:
            undo_renames(folder)
        else:
            rename_files(folder)
    except KeyboardInterrupt:
        print()
        print("Stopped. Nothing was left half-renamed: any renames from this run were put back.")
        raise SystemExit(1)
    except (OSError, ValueError) as err:
        print()
        print(f"⚠️  Something went wrong: {err}")
        print("No file was left half-renamed: any renames from this run were put back")
        print("(see any warnings above).")
        print("If a file is open in another program (like Photos or Excel), close it and try again.")
        print()
        raise SystemExit(1)


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

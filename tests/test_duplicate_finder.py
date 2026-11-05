"""Tests for duplicate_finder.py."""

import csv
import hashlib
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

import duplicate_finder
from conftest import PROJECT_ROOT, run_script

OLD, MIDDLE, NEW = 1_000_000_000, 1_500_000_000, 2_000_000_000


def setup_folder(workspace):
    folder = workspace / "files_to_check"
    folder.mkdir()
    return folder


def make_file(path, content, mtime=None):
    """Create a file (and its folders) with the given text or bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def make_photo(seed=0, size=(800, 600)):
    """A photo-like picture: soft colored shapes plus a little grain."""
    width, height = size
    rng = random.Random(seed)
    small = Image.frombytes("RGB", (16, 12), rng.randbytes(16 * 12 * 3))
    img = small.resize(size, Image.BICUBIC)
    grain = Image.frombytes("RGB", size, rng.randbytes(width * height * 3))
    return Image.blend(img, grain, 0.08).filter(ImageFilter.GaussianBlur(1))


def answer_with(monkeypatch, *answers):
    """Pretend the user types these answers, in order, at each question."""
    replies = iter(answers)

    def fake_input(prompt=""):
        print(prompt)
        try:
            return next(replies)
        except StopIteration:
            raise AssertionError(f"Unexpected question: {prompt}") from None

    monkeypatch.setattr("builtins.input", fake_input)


def fingerprints(root):
    """{path inside root: (hash of contents, last-modified time)} for every file."""
    result = {}
    for path in Path(root).rglob("*"):
        if path.is_file():
            info = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(root).as_posix()] = (digest, info.st_mtime_ns)
    return result


def files_in(root):
    return sorted(fingerprints(root)) if Path(root).exists() else []


def read_report(workspace):
    with open(workspace / "duplicates_report.csv", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def run_in_terminal(cwd, typed_text, *options):
    """Run the tool like a user would, typing the given text into the terminal."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "duplicate_finder.py"), *options],
        cwd=cwd,
        input=typed_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


REVIEW = Path("duplicates_review") / "files_to_check"


# ---------------------------------------------------------------------------
# Exact copies
# ---------------------------------------------------------------------------

def test_exact_copies_across_subfolders_are_moved_keeping_their_folders(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "Taxes" / "report.pdf", "tax report", OLD)
    make_file(folder / "Backup" / "2023" / "report.pdf", "tax report", NEW)
    make_file(folder / "Backup" / "notes.txt", "unique notes")

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Move 1 duplicate copy (10 bytes) to the review folder? Type y to continue:" in out
    assert "All done!" in out
    assert "delete the review folder yourself" in out
    assert files_in(folder) == ["Backup/notes.txt", "Taxes/report.pdf"]
    moved = workspace / REVIEW / "Backup" / "2023" / "report.pdf"
    assert moved.read_text() == "tax report"


def test_different_names_with_the_same_content_are_copies(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "report.pdf", b"%PDF same bytes", OLD)
    make_file(folder / "report (1).pdf", b"%PDF same bytes", NEW)
    make_file(folder / "IMG_2041.jpg", b"photo bytes", MIDDLE)
    make_file(folder / "IMG_2041 copy.jpg", b"photo bytes", MIDDLE)  # same date

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Move 2 duplicate copies" in out
    # Same date: the shorter name wins, so the result never depends on luck
    assert files_in(folder) == ["IMG_2041.jpg", "report.pdf"]
    assert files_in(workspace / REVIEW) == ["IMG_2041 copy.jpg", "report (1).pdf"]


def test_same_name_with_different_content_is_not_a_copy(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "January" / "notes.txt", "January notes")
    make_file(folder / "February" / "notes.txt", "February note")  # same size, too
    before = fingerprints(folder)

    answer_with(monkeypatch)  # no questions should be asked
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "No duplicates found" in out
    assert fingerprints(folder) == before
    assert not (workspace / "duplicates_review").exists()


def test_big_files_are_compared_in_full_not_just_start_and_end(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    size = 3 * duplicate_finder.QUICK_CHECK_BYTES
    same = bytes(size)
    differs_in_the_middle = bytearray(size)
    differs_in_the_middle[size // 2] = 1
    make_file(folder / "video.mp4", same, OLD)
    make_file(folder / "video copy.mp4", same, NEW)
    make_file(folder / "video edited.mp4", bytes(differs_in_the_middle), NEW)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Double-checking 3 possible copies byte by byte..." in out
    assert files_in(folder) == ["video edited.mp4", "video.mp4"]
    assert files_in(workspace / REVIEW) == ["video copy.mp4"]


@pytest.mark.parametrize(
    "rule, kept",
    [("oldest", "b/old.txt"), ("newest", "new.txt"), ("shortest_path", "new.txt")],
)
def test_keep_rules(workspace, monkeypatch, rule, kept):
    folder = setup_folder(workspace)
    make_file(folder / "b" / "old.txt", "same", OLD)
    make_file(folder / "new.txt", "same", NEW)
    make_file(folder / "a" / "b" / "middle.txt", "same", MIDDLE)
    monkeypatch.setattr(duplicate_finder, "KEEP", rule)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    assert files_in(folder) == [kept]


def test_misspelled_keep_setting_falls_back_to_oldest(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "old.txt", "same", OLD)
    make_file(folder / "new.txt", "same", NEW)
    monkeypatch.setattr(duplicate_finder, "KEEP", "biggest")

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    assert "isn't 'oldest', 'newest' or 'shortest_path'" in capsys.readouterr().out
    assert files_in(folder) == ["old.txt"]


def test_empty_hidden_and_system_files_are_ignored(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "empty1.txt", b"")
    make_file(folder / "empty2.txt", b"")
    make_file(folder / ".hidden_a", "secret")
    make_file(folder / ".hidden_b", "secret")
    make_file(folder / ".git" / "objects" / "x", "secret")
    make_file(folder / "Thumbs.db", "secret")
    make_file(folder / "desktop.ini", "secret")
    make_file(folder / "movie.mp4.crdownload", "secret")
    make_file(folder / "Photos Library.photoslibrary" / "originals" / "x.jpg", "secret")
    make_file(folder / "node_modules" / "pkg" / "index.js", "secret")
    make_file(folder / "real.txt", "secret")
    before = fingerprints(folder)

    answer_with(monkeypatch)
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Found 1 file to check" in out
    assert "No duplicates found" in out
    assert fingerprints(folder) == before


def test_shortcuts_and_hard_links_are_not_treated_as_copies(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    original = make_file(folder / "photo.jpg", "picture")
    try:
        os.symlink(original, folder / "shortcut.jpg")
        os.link(original, folder / "hard link.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("this computer doesn't allow creating links")

    answer_with(monkeypatch)
    duplicate_finder.main([])

    assert "No duplicates found" in capsys.readouterr().out
    assert sorted(os.listdir(folder)) == ["hard link.jpg", "photo.jpg", "shortcut.jpg"]


def test_review_folder_inside_the_checked_folder_is_skipped(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same")
    make_file(folder / "duplicates_review" / "a.txt", "same")

    answer_with(monkeypatch)
    duplicate_finder.main([])

    assert "No duplicates found" in capsys.readouterr().out


def test_progress_is_shown_for_big_folders(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    for i in range(6):
        make_file(folder / f"file{i}.txt", f"content {i}")  # same size, different
    monkeypatch.setattr(duplicate_finder, "PROGRESS_EVERY", 2)

    answer_with(monkeypatch)
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Comparing 6 files that share their size with another file..." in out
    assert "Checked 2 of 6 files..." in out
    assert "Checked 6 of 6 files." in out


# ---------------------------------------------------------------------------
# Similar photos
# ---------------------------------------------------------------------------

def make_photo_set(folder):
    """One photo saved five ways, plus a different photo."""
    photo = make_photo(seed=1)
    photo.save(folder / "beach.png")
    (folder / "Shared").mkdir()
    photo.resize((400, 300), Image.LANCZOS).save(folder / "Shared" / "beach_small.jpg", quality=70)
    photo.save(folder / "beach_recompressed.jpg", quality=30)
    photo.convert("RGB").save(folder / "beach_converted.jpg", quality=90)
    # Stored sideways with a "rotate me" note, the way phones do it
    exif = Image.Exif()
    exif[duplicate_finder.ORIENTATION_TAG] = 6
    photo.rotate(90, expand=True).save(folder / "beach_phone.jpg", quality=85, exif=exif)
    make_photo(seed=2).save(folder / "mountain.jpg", quality=90)


def test_similar_photos_are_listed_but_not_moved_by_default(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_photo_set(folder)
    before = fingerprints(folder)

    answer_with(monkeypatch)  # nothing to move, so no question
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Similar photos:  1 group, 4 photos" in out
    assert "only listed in the report" in out
    assert "check them by eye" in out
    assert fingerprints(folder) == before

    rows = read_report(workspace)
    assert {row["reason"] for row in rows} == {"similar"}
    assert {row["kept_file"] for row in rows} == {str(Path("files_to_check") / "beach.png")}
    assert sorted(Path(row["duplicate_file"]).name for row in rows) == [
        "beach_converted.jpg", "beach_phone.jpg", "beach_recompressed.jpg", "beach_small.jpg",
    ]
    assert all(row["plan"] == "only listed - check by eye" for row in rows)


def test_similar_photos_are_moved_when_turned_on(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_photo_set(folder)
    monkeypatch.setattr(duplicate_finder, "MOVE_SIMILAR_PHOTOS", True)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Move 4 duplicate copies" in out
    assert "(looks like beach.png)" in out
    # The version with the most pixels (and biggest file) stays
    assert files_in(folder) == ["beach.png", "mountain.jpg"]
    assert "Shared/beach_small.jpg" in files_in(workspace / REVIEW)


def test_different_photos_are_not_similar(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    for seed in range(5):
        make_photo(seed=seed).save(folder / f"photo{seed}.jpg", quality=85)

    answer_with(monkeypatch)
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Looking for similar photos among 5 pictures..." in out
    assert "No duplicates found" in out


def test_plain_pictures_are_not_matched(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    Image.new("RGB", (300, 200), "white").save(folder / "blank.png")
    Image.new("RGB", (300, 200), (250, 250, 250)).save(folder / "almost_blank.jpg")

    answer_with(monkeypatch)
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "2 pictures couldn't be compared" in out
    assert "No duplicates found" in out


def test_exact_and_similar_together_in_the_report(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_photo_set(folder)
    make_file(folder / "report.pdf", "pdf", OLD)
    make_file(folder / "Downloads" / "report (1).pdf", "pdf", NEW)

    answer_with(monkeypatch, "n")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Exact copies:    1 group, 1 extra copy, 3 bytes" in out
    assert "Biggest groups:" in out
    rows = read_report(workspace)
    assert list(rows[0]) == [
        "group", "kept_file", "duplicate_file", "size", "size_bytes", "reason", "plan",
    ]
    exact = [row for row in rows if row["reason"] == "exact"]
    assert exact == [{
        "group": "1",
        "kept_file": str(Path("files_to_check") / "report.pdf"),
        "duplicate_file": str(Path("files_to_check") / "Downloads" / "report (1).pdf"),
        "size": "3 bytes",
        "size_bytes": "3",
        "reason": "exact",
        "plan": "move to review folder",
    }]
    assert {row["group"] for row in rows if row["reason"] == "similar"} == {"2"}


def test_summary_shows_space_and_biggest_groups(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    for i in range(7):
        content = bytes([i]) * (1024 * 1024 * (i + 1))
        make_file(folder / f"big{i}.bin", content, OLD)
        make_file(folder / "copies" / f"big{i}.bin", content, NEW)

    answer_with(monkeypatch, "n")
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "Space you could free: 28.0 MB" in out
    assert "1. big6.bin  (1 extra copy, 7.0 MB)" in out
    assert "5. big2.bin  (1 extra copy, 3.0 MB)" in out
    assert "big1.bin  (1 extra copy" not in out  # only the top 5 are listed


# ---------------------------------------------------------------------------
# Cancel and undo
# ---------------------------------------------------------------------------

def test_cancel_changes_nothing(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "sub" / "a.txt", "same", NEW)
    before = fingerprints(folder)

    answer_with(monkeypatch, "n")
    duplicate_finder.main([])

    assert "Cancelled — nothing was moved." in capsys.readouterr().out
    assert fingerprints(folder) == before
    assert not (workspace / "duplicates_review").exists()


def test_undo_puts_every_file_back_exactly(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "report.pdf", "pdf", OLD)
    make_file(folder / "report (1).pdf", "pdf", NEW)
    make_file(folder / "Trip" / "Day 1" / "IMG_1.jpg", "img", OLD)
    make_file(folder / "Trip" / "Backup" / "IMG_1.jpg", "img", NEW)
    make_file(folder / "Café menu.txt", "menu", OLD)
    make_file(folder / "Old" / "Café menu.txt", "menu", NEW)
    before = fingerprints(folder)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])
    assert "python duplicate_finder.py --undo" in capsys.readouterr().out
    assert len(files_in(workspace / REVIEW)) == 3
    assert (workspace / "duplicates_review" / ".duplicates_undo_log.csv").exists()

    answer_with(monkeypatch, "y")
    duplicate_finder.main(["--undo"])

    out = capsys.readouterr().out
    assert "Put back 3 files from the review folder? Type y to continue:" in out
    assert "3 files are back where they were." in out
    assert fingerprints(folder) == before
    # Only the empty folders this tool made are tidied away
    assert not (workspace / "duplicates_review").exists()


def test_undo_after_two_runs_puts_everything_back(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "a copy.txt", "same", NEW)
    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    make_file(folder / "b.txt", "other", OLD)
    make_file(folder / "sub" / "b.txt", "other", NEW)
    answer_with(monkeypatch, "y")
    duplicate_finder.main([])
    assert files_in(folder) == ["a.txt", "b.txt"]

    answer_with(monkeypatch, "y")
    duplicate_finder.main(["--undo"])

    assert files_in(folder) == ["a copy.txt", "a.txt", "b.txt", "sub/b.txt"]
    assert (folder / "a copy.txt").read_text() == "same"
    assert not (workspace / "duplicates_review").exists()


def test_a_taken_review_spot_gets_a_new_name_instead_of_overwriting(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "copy.txt", "same", NEW)
    already_there = make_file(workspace / REVIEW / "copy.txt", "something else")

    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    assert already_there.read_text() == "something else"
    assert (workspace / REVIEW / "copy (2).txt").read_text() == "same"


def test_undo_refuses_when_the_original_spot_is_taken(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "b.txt", "same", NEW)
    make_file(folder / "c.txt", "other", OLD)
    make_file(folder / "d.txt", "other", NEW)
    answer_with(monkeypatch, "y")
    duplicate_finder.main([])

    make_file(folder / "b.txt", "a new file the user made")
    after_move = fingerprints(workspace)
    capsys.readouterr()

    answer_with(monkeypatch)  # must stop before asking
    duplicate_finder.main(["--undo"])

    out = capsys.readouterr().out
    assert "Stopped before changing anything" in out
    assert "files_to_check/b.txt' is taken" in out
    assert fingerprints(workspace) == after_move


def test_undo_cancel_changes_nothing(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "b.txt", "same", NEW)
    answer_with(monkeypatch, "y")
    duplicate_finder.main([])
    after_move = fingerprints(workspace)

    answer_with(monkeypatch, "no")
    duplicate_finder.main(["--undo"])

    assert "Cancelled — nothing was moved." in capsys.readouterr().out
    assert fingerprints(workspace) == after_move


def test_undo_without_a_log_explains(workspace, capsys):
    duplicate_finder.main(["--undo"])

    assert "Nothing to undo" in capsys.readouterr().out
    assert not (workspace / "files_to_check").exists()


def test_a_file_that_changed_after_the_check_is_not_moved(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    copy = make_file(folder / "b.txt", "same", NEW)

    def edit_then_confirm(prompt=""):
        print(prompt)
        copy.write_text("edited meanwhile")
        return "y"

    monkeypatch.setattr("builtins.input", edit_then_confirm)
    duplicate_finder.main([])

    out = capsys.readouterr().out
    assert "b.txt: it changed after the check" in out
    assert copy.read_text() == "edited meanwhile"
    assert not (workspace / "duplicates_review" / ".duplicates_undo_log.csv").exists()


# ---------------------------------------------------------------------------
# Choosing the folder
# ---------------------------------------------------------------------------

def test_a_folder_path_with_spaces_on_the_command_line(workspace, monkeypatch, capsys):
    folder = workspace / "My Downloads"
    make_file(folder / "report.pdf", "pdf", OLD)
    make_file(folder / "report (1).pdf", "pdf", NEW)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([str(folder)])

    out = capsys.readouterr().out
    assert files_in(folder) == ["report.pdf"]
    # The review folder sits next to the checked folder; the report stays here
    assert (workspace / "duplicates_review" / "My Downloads" / "report (1).pdf").exists()
    assert (workspace / "duplicates_report.csv").exists()
    assert f'python duplicate_finder.py --undo "{folder.resolve()}"' in out

    answer_with(monkeypatch, "y")
    duplicate_finder.main(["--undo", str(folder)])
    assert files_in(folder) == ["report (1).pdf", "report.pdf"]


def test_plain_undo_remembers_the_last_folder_checked(workspace, monkeypatch, capsys):
    downloads = workspace / "Downloads"
    make_file(downloads / "a.txt", "same", OLD)
    make_file(downloads / "b.txt", "same", NEW)
    project = workspace / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    before = fingerprints(downloads)

    answer_with(monkeypatch, "y")
    duplicate_finder.main([str(downloads)])
    assert files_in(downloads) == ["a.txt"]

    answer_with(monkeypatch, "y")
    duplicate_finder.main(["--undo"])

    assert "Using the review folder from the last time files were moved" in capsys.readouterr().out
    assert fingerprints(downloads) == before
    assert not (workspace / "duplicates_review").exists()
    assert not (project / ".duplicates_last_run.txt").exists()


def test_a_path_with_spaces_but_no_quotes_still_works(workspace, monkeypatch, capsys):
    folder = workspace / "My Old Photos"
    make_file(folder / "a.jpg", "same", OLD)
    make_file(folder / "b.jpg", "same", NEW)

    answer_with(monkeypatch, "n")
    duplicate_finder.main(str(folder).split(" "))

    out = capsys.readouterr().out
    assert "put quotes around folder paths that contain spaces" in out
    assert "Move 1 duplicate copy" in out


def test_quotes_and_tilde_are_understood(workspace, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(workspace))
    monkeypatch.setenv("USERPROFILE", str(workspace))
    make_file(workspace / "Downloads" / "a.txt", "same", OLD)
    make_file(workspace / "Downloads" / "b.txt", "same", NEW)

    answer_with(monkeypatch, "n")
    duplicate_finder.main(['"~/Downloads"'])

    assert "Move 1 duplicate copy" in capsys.readouterr().out


def test_a_missing_folder_is_explained(workspace, capsys):
    with pytest.raises(SystemExit):
        duplicate_finder.main([str(workspace / "Nope")])

    assert "Couldn't find a folder called" in capsys.readouterr().out


def system_folder():
    if sys.platform == "win32":
        return os.environ.get("SystemRoot", r"C:\Windows")
    return "/usr"


@pytest.mark.parametrize(
    "target",
    [
        lambda ws: ws.anchor,  # the top of the whole drive
        lambda ws: str(Path.home()),
        lambda ws: "~",
        lambda ws: system_folder(),
        lambda ws: str(Path(system_folder()) / ("System32" if sys.platform == "win32" else "share")),
        lambda ws: str(ws / "duplicates_review"),
    ],
)
def test_dangerous_folders_are_refused(workspace, capsys, target):
    (workspace / "duplicates_review").mkdir()

    with pytest.raises(SystemExit) as stopped:
        duplicate_finder.main([target(workspace)])

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "⚠️" in out
    assert "Listing files" not in out
    assert not (workspace / "duplicates_report.csv").exists()


def test_safety_check_allows_normal_folders_only(workspace):
    assert duplicate_finder.safety_problem(workspace / "files_to_check") is None
    assert duplicate_finder.safety_problem(workspace / "My Photos" / "2024") is None
    assert "home folder" in duplicate_finder.safety_problem(Path.home())
    for app_data in (Path.home() / "Library" / "Mail", Path.home() / "AppData" / "Roaming"):
        assert "system or app folder" in duplicate_finder.safety_problem(app_data)


def test_creates_folder_and_explains_next_steps(workspace, monkeypatch, capsys):
    answer_with(monkeypatch)  # no questions should be asked

    duplicate_finder.main([])

    assert (workspace / "files_to_check").is_dir()
    out = capsys.readouterr().out
    assert "Created folder" in out
    assert "No files found to check yet." in out


def test_unknown_option_is_explained(workspace, capsys):
    with pytest.raises(SystemExit) as stopped:
        duplicate_finder.main(["--delete"])

    assert stopped.value.code == 2
    assert "Unknown option: --delete" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Running from the terminal
# ---------------------------------------------------------------------------

def test_empty_folder_from_the_terminal(workspace):
    result = run_script("duplicate_finder.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "No files found to check yet." in result.stdout


def test_runs_from_the_terminal(workspace):
    folder = setup_folder(workspace)
    make_file(folder / "report.pdf", "pdf", OLD)
    make_file(folder / "Downloads" / "report (1).pdf", "pdf", NEW)
    make_photo(seed=3).save(folder / "IMG_2041.jpg", quality=90)
    (folder / "IMG_2041 copy.jpg").write_bytes((folder / "IMG_2041.jpg").read_bytes())
    os.utime(folder / "IMG_2041 copy.jpg", (NEW, NEW))
    before = fingerprints(folder)

    result = run_in_terminal(workspace, "y\n")

    assert result.returncode == 0, result.stderr
    assert "Tool: Duplicate File Finder" in result.stdout
    assert "Move 2 duplicate copies" in result.stdout
    assert "All done!" in result.stdout
    assert files_in(folder) == ["IMG_2041.jpg", "report.pdf"]

    result = run_in_terminal(workspace, "y\n", "--undo")

    assert result.returncode == 0, result.stderr
    assert fingerprints(folder) == before


def test_terminal_path_with_spaces(workspace):
    folder = workspace / "Holiday Photos 2024"
    make_file(folder / "a.jpg", "same", OLD)
    make_file(folder / "b.jpg", "same", NEW)

    # A list argument reaches the script as ONE piece, exactly like a quoted path
    result = run_in_terminal(workspace, "y\n", str(folder))

    assert result.returncode == 0, result.stderr
    assert (workspace / "duplicates_review" / "Holiday Photos 2024" / "b.jpg").exists()


def test_terminal_refuses_the_home_folder(workspace):
    result = run_in_terminal(workspace, "", "~")

    assert result.returncode == 1
    assert "whole home folder" in result.stdout


def test_terminal_input_ending_early_cancels(workspace):
    folder = setup_folder(workspace)
    make_file(folder / "a.txt", "same", OLD)
    make_file(folder / "b.txt", "same", NEW)

    result = run_in_terminal(workspace, "")

    assert result.returncode == 0, result.stderr
    # Plain-ASCII check: a Windows terminal may not show the dash character
    assert "nothing was moved." in result.stdout
    assert files_in(folder) == ["a.txt", "b.txt"]

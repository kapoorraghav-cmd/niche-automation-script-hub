"""Tests for bulk_renamer.py."""

import hashlib
import os
import subprocess
import sys

import pytest

import bulk_renamer
from conftest import PROJECT_ROOT, run_script


def setup_folder(workspace):
    folder = workspace / "files_to_rename"
    folder.mkdir()
    return folder


def make_files(folder, *names):
    """Create small files whose contents are their own names (so we can track them)."""
    for name in names:
        (folder / name).write_text(f"contents of {name}")


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


def visible_names(folder):
    """Real names on disk (exact capital letters), hidden files excluded."""
    return sorted(name for name in os.listdir(folder) if not name.startswith("."))


def fingerprints(folder):
    """{file name: hash of its contents} for every file in the folder."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()
    }


def run_in_terminal(cwd, typed_text, *options):
    """Run the tool like a user would, typing the given text into the terminal."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "bulk_renamer.py"), *options],
        cwd=cwd,
        input=typed_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_natural_sort_puts_2_before_10(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "DCIM_10.jpg", "DCIM_2.jpg", "DCIM_1.jpg", "dcim_00003.jpg")

    answer_with(monkeypatch, "Project_Photos", "y")
    bulk_renamer.main([])

    def contents(n):
        return (folder / f"Project_Photos_00{n}.jpg").read_text()

    assert contents(1) == "contents of DCIM_1.jpg"
    assert contents(2) == "contents of DCIM_2.jpg"
    assert contents(3) == "contents of dcim_00003.jpg"
    assert contents(4) == "contents of DCIM_10.jpg"


def test_nine_files_get_three_digit_numbers(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, *[f"img{i}.png" for i in range(1, 10)])

    answer_with(monkeypatch, "Trip", "y")
    bulk_renamer.main([])

    assert visible_names(folder) == [f"Trip_00{i}.png" for i in range(1, 10)]


def test_a_thousand_files_get_four_digit_numbers_and_progress(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, *[f"scan{i}.pdf" for i in range(1, 1001)])

    answer_with(monkeypatch, "Scan", "y")
    bulk_renamer.main([])

    names = visible_names(folder)
    assert len(names) == 1000
    assert names[0] == "Scan_0001.pdf"
    assert names[-1] == "Scan_1000.pdf"
    assert (folder / "Scan_0010.pdf").read_text() == "contents of scan10.pdf"
    out = capsys.readouterr().out
    assert "Renamed 50 of 1000 files..." in out
    assert "Renamed 1000 of 1000 file(s)." in out


def test_original_extensions_are_kept_exactly(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "a.JPG", "b.jpeg", "c.PDF", "d_no_extension")

    answer_with(monkeypatch, "Mixed", "y")
    bulk_renamer.main([])

    assert visible_names(folder) == ["Mixed_001.JPG", "Mixed_002.jpeg", "Mixed_003.PDF", "Mixed_004"]


def test_preview_then_cancel_changes_nothing(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, *[f"DCIM_{i:05d}.jpg" for i in range(1, 16)])
    before = fingerprints(folder)

    answer_with(monkeypatch, "Project_Photos", "n")
    bulk_renamer.main([])

    out = capsys.readouterr().out
    assert "DCIM_00001.jpg  →  Project_Photos_001.jpg" in out
    assert "... and 5 more" in out
    assert "Rename these 15 files? Type y to continue:" in out
    assert "Cancelled — nothing was renamed." in out
    assert fingerprints(folder) == before
    assert not (folder / ".rename_undo_log.csv").exists()


def test_invalid_base_names_are_asked_again(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "x.txt")

    answer_with(monkeypatch, "   ", "bad/name", 'what?"', "Photos.", ".hidden", "  My  Photos  ", "y")
    bulk_renamer.main([])

    out = capsys.readouterr().out
    assert "can't be empty" in out
    assert "can't contain these characters: /" in out
    assert 'can\'t contain these characters: " ?' in out
    assert "can't end with a dot" in out
    assert "can't start with a dot" in out
    assert "Using: My_Photos" in out
    assert visible_names(folder) == ["My_Photos_001.txt"]


def test_clean_base_name_rules():
    assert bulk_renamer.clean_base_name("  Project Photos ") == ("Project_Photos", None)
    assert bulk_renamer.clean_base_name("Q3:report")[1] is not None
    assert bulk_renamer.clean_base_name("a" * 101)[1] is not None
    assert bulk_renamer.clean_base_name("Café_2024")[1] is None


def test_clash_with_an_item_that_is_not_being_renamed_stops_safely(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "a.jpg", "b.jpg")
    # A sub-folder is never renamed, so its name can't be given to a file
    (folder / "Project_Photos_001.jpg").mkdir()
    before = fingerprints(folder)

    answer_with(monkeypatch, "Project_Photos")
    bulk_renamer.main([])

    out = capsys.readouterr().out
    assert "Stopped before changing anything" in out
    assert "'Project_Photos_001.jpg' already exists" in out
    assert fingerprints(folder) == before
    assert (folder / "Project_Photos_001.jpg").is_dir()
    assert not (folder / ".rename_undo_log.csv").exists()


def test_running_again_on_renamed_files_changes_nothing(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "one.txt", "two.txt")
    answer_with(monkeypatch, "Notes", "y")
    bulk_renamer.main([])
    log_before = (folder / ".rename_undo_log.csv").read_bytes()
    files_before = fingerprints(folder)
    capsys.readouterr()

    # Only the name question should be asked — there is nothing to confirm
    answer_with(monkeypatch, "Notes")
    bulk_renamer.main([])

    assert "Nothing to do — all 2 file(s) already have these names." in capsys.readouterr().out
    assert fingerprints(folder) == files_before
    assert (folder / ".rename_undo_log.csv").read_bytes() == log_before


def test_only_files_needing_a_change_are_renamed(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "Notes_001.txt", "zzz.txt")

    answer_with(monkeypatch, "Notes", "y")
    bulk_renamer.main([])

    out = capsys.readouterr().out
    assert "1 file(s) already have the right name" in out
    assert "Rename these 1 files?" in out
    assert visible_names(folder) == ["Notes_001.txt", "Notes_002.txt"]


def test_case_only_rename_works(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "project_photos_001.jpg", "project_photos_002.jpg")

    answer_with(monkeypatch, "Project_Photos", "y")
    bulk_renamer.main([])

    assert visible_names(folder) == ["Project_Photos_001.jpg", "Project_Photos_002.jpg"]
    assert (folder / "Project_Photos_002.jpg").read_text() == "contents of project_photos_002.jpg"


def test_sort_by_date_numbers_oldest_first(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "a.jpg", "b.jpg", "c.jpg")
    os.utime(folder / "a.jpg", (3_000_000, 3_000_000))  # newest
    os.utime(folder / "b.jpg", (1_000_000, 1_000_000))  # oldest
    os.utime(folder / "c.jpg", (2_000_000, 2_000_000))
    monkeypatch.setattr(bulk_renamer, "SORT_BY", "date")

    answer_with(monkeypatch, "Shot", "y")
    bulk_renamer.main([])

    assert (folder / "Shot_001.jpg").read_text() == "contents of b.jpg"
    assert (folder / "Shot_002.jpg").read_text() == "contents of c.jpg"
    assert (folder / "Shot_003.jpg").read_text() == "contents of a.jpg"


def test_files_can_swap_names_safely(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "Pic_001.jpg", "Pic_002.jpg")
    # By date, Pic_002 is older, so the two files must swap names
    os.utime(folder / "Pic_001.jpg", (2_000_000, 2_000_000))
    os.utime(folder / "Pic_002.jpg", (1_000_000, 1_000_000))
    monkeypatch.setattr(bulk_renamer, "SORT_BY", "date")

    answer_with(monkeypatch, "Pic", "y")
    bulk_renamer.main([])

    assert (folder / "Pic_001.jpg").read_text() == "contents of Pic_002.jpg"
    assert (folder / "Pic_002.jpg").read_text() == "contents of Pic_001.jpg"


def test_undo_restores_original_names_and_contents(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "DCIM_2.jpg", "DCIM_10.jpg", "report final.pdf", "Café menu.JPG")
    before = fingerprints(folder)

    answer_with(monkeypatch, "Project_Photos", "y")
    bulk_renamer.main([])
    assert "python bulk_renamer.py --undo" in capsys.readouterr().out
    assert set(fingerprints(folder)) != set(before)

    answer_with(monkeypatch, "y")
    bulk_renamer.main(["--undo"])

    out = capsys.readouterr().out
    assert "Put back the original names of these 4 files?" in out
    assert "4 file(s) have their original names back." in out
    assert fingerprints(folder) == before
    assert not (folder / ".rename_undo_log.csv").exists()


def test_undo_after_two_runs_goes_back_to_the_very_first_names(workspace, monkeypatch):
    folder = setup_folder(workspace)
    make_files(folder, "b.txt", "a.txt", "c.txt")
    before = fingerprints(folder)

    answer_with(monkeypatch, "First", "y")
    bulk_renamer.main([])
    make_files(folder, "added_later.txt")
    answer_with(monkeypatch, "Second", "y")
    bulk_renamer.main([])
    assert visible_names(folder) == [f"Second_00{i}.txt" for i in range(1, 5)]

    answer_with(monkeypatch, "y")
    bulk_renamer.main(["--undo"])

    expected = dict(before)
    expected["added_later.txt"] = hashlib.sha256(b"contents of added_later.txt").hexdigest()
    assert fingerprints(folder) == expected


def test_undo_cancel_and_undo_clash_change_nothing(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "DCIM_1.jpg", "DCIM_2.jpg")
    answer_with(monkeypatch, "Trip", "y")
    bulk_renamer.main([])
    after_rename = fingerprints(folder)

    answer_with(monkeypatch, "no")
    bulk_renamer.main(["--undo"])
    assert fingerprints(folder) == after_rename

    # A new file now uses one of the original names, so undo must not run
    make_files(folder, "DCIM_1.jpg")
    capsys.readouterr()
    answer_with(monkeypatch)
    bulk_renamer.main(["--undo"])

    assert "Stopped before changing anything" in capsys.readouterr().out
    after_rename["DCIM_1.jpg"] = hashlib.sha256(b"contents of DCIM_1.jpg").hexdigest()
    assert fingerprints(folder) == after_rename


def test_undo_without_a_log_explains(workspace, capsys):
    setup_folder(workspace)

    bulk_renamer.main(["--undo"])

    assert "Nothing to undo" in capsys.readouterr().out


def test_hidden_files_and_folders_are_ignored(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "photo.jpg", ".DS_Store", ".secret.jpg", "Thumbs.db", "desktop.ini")
    (folder / "old").mkdir()
    make_files(folder / "old", "inside.jpg")

    answer_with(monkeypatch, "Pic", "y")
    bulk_renamer.main([])

    assert "Found 1 file(s)" in capsys.readouterr().out
    assert sorted(os.listdir(folder)) == sorted(
        [".DS_Store", ".rename_undo_log.csv", ".secret.jpg", "Pic_001.jpg", "Thumbs.db",
         "desktop.ini", "old"]
    )
    assert os.listdir(folder / "old") == ["inside.jpg"]


def test_a_failure_halfway_puts_every_name_back(workspace, monkeypatch, capsys):
    folder = setup_folder(workspace)
    make_files(folder, *[f"f{i}.txt" for i in range(1, 6)])
    before = fingerprints(folder)

    real_move = bulk_renamer.move_file
    calls = []

    def flaky_move(folder_path, old_name, new_name):
        calls.append(old_name)
        if len(calls) == 8:  # partway through the second phase
            raise PermissionError("file is open in another program")
        real_move(folder_path, old_name, new_name)

    monkeypatch.setattr(bulk_renamer, "move_file", flaky_move)
    answer_with(monkeypatch, "Doc", "y")
    with pytest.raises(SystemExit):
        bulk_renamer.main([])

    assert "file is open in another program" in capsys.readouterr().out
    assert fingerprints(folder) == before
    assert not (folder / ".rename_undo_log.csv").exists()


def test_interrupted_run_leftovers_stop_the_tool(workspace, capsys):
    folder = setup_folder(workspace)
    make_files(folder, "a.jpg.bulk_renamer_tmp", "b.jpg")
    before = fingerprints(folder)

    with pytest.raises(SystemExit):
        bulk_renamer.main([])

    assert "an earlier rename was interrupted" in capsys.readouterr().out
    assert fingerprints(folder) == before


def test_creates_folder_and_explains_next_steps(workspace, monkeypatch, capsys):
    answer_with(monkeypatch)  # no questions should be asked

    bulk_renamer.main([])

    assert (workspace / "files_to_rename").is_dir()
    out = capsys.readouterr().out
    assert "Created folder" in out
    assert "No files found to rename yet." in out


def test_empty_folder_from_the_terminal(workspace):
    result = run_script("bulk_renamer.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "No files found to rename yet." in result.stdout


def test_runs_from_the_terminal(workspace):
    folder = setup_folder(workspace)
    make_files(folder, "DCIM_10.jpg", "DCIM_2.jpg")
    before = fingerprints(folder)

    result = run_in_terminal(workspace, "Project Photos\ny\n")

    assert result.returncode == 0, result.stderr
    assert "Rename these 2 files? Type y to continue:" in result.stdout
    assert "All done!" in result.stdout
    assert (folder / "Project_Photos_001.jpg").read_text() == "contents of DCIM_2.jpg"

    result = run_in_terminal(workspace, "y\n", "--undo")

    assert result.returncode == 0, result.stderr
    assert fingerprints(folder) == before


def test_terminal_input_ending_early_cancels(workspace):
    folder = setup_folder(workspace)
    make_files(folder, "a.txt")

    result = run_in_terminal(workspace, "Notes\n")

    assert result.returncode == 0, result.stderr
    # Plain-ASCII check: a Windows terminal may not show the dash character
    assert "nothing was renamed." in result.stdout
    assert visible_names(folder) == ["a.txt"]

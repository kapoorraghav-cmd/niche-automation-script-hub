"""Tests for excel_cleaner.py."""

import hashlib
from datetime import datetime

import pandas as pd

import excel_cleaner
from conftest import run_script


def setup_input(workspace):
    folder = workspace / "input_spreadsheets"
    folder.mkdir()
    return folder


def write_csv(path, text, encoding="utf-8"):
    path.write_text(text, encoding=encoding)
    return path


def read_cleaned_csv(workspace, name):
    """Read a cleaned CSV back exactly as text, cell by cell."""
    return pd.read_csv(
        workspace / "cleaned_spreadsheets" / name,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )


def test_removes_completely_duplicate_rows(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(
        inputs / "contacts.csv",
        "Name,Email\nAda,ada@example.com\nBob,bob@example.com\nAda,ada@example.com\n",
    )

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "contacts_cleaned.csv")
    assert cleaned["Name"].tolist() == ["Ada", "Bob"]
    assert "Removed 1 duplicate row(s)" in capsys.readouterr().out


def test_keeps_rows_that_differ_in_any_cell(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "orders.csv", "Name,Amount\nAda,10\nAda,11\n")

    excel_cleaner.main()

    assert len(read_cleaned_csv(workspace, "orders_cleaned.csv")) == 2


def test_mixed_date_formats_become_yyyy_mm_dd(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(
        inputs / "sales.csv",
        "Order Date,Item\n"
        "01/15/2024,Tea\n"
        "2024-02-03,Coffee\n"
        '"March 5, 2024",Cake\n'
        "15 Apr 2024,Juice\n",
    )

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "sales_cleaned.csv")
    assert cleaned["Order Date"].tolist() == [
        "2024-01-15",
        "2024-02-03",
        "2024-03-05",
        "2024-04-15",
    ]
    assert "Standardized dates in: Order Date" in capsys.readouterr().out


def test_non_date_text_in_a_date_column_is_kept(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "tasks.csv", "Due Date\n01/15/2024\nTBD\n2024-02-03\n")

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "tasks_cleaned.csv")
    assert cleaned["Due Date"].tolist() == ["2024-01-15", "TBD", "2024-02-03"]


def test_times_of_day_are_not_lost(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "log.csv", "Timestamp\n2024-01-15 14:30\n01/16/2024 09:05\n")

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "log_cleaned.csv")
    assert cleaned["Timestamp"].tolist() == ["2024-01-15 14:30", "2024-01-16 09:05"]


def test_other_data_is_left_exactly_as_typed(workspace):
    inputs = setup_input(workspace)
    original = (
        "Employee ID,Year,Overtime Hours,Weekday,Start Time,Status,Price,Phone\n"
        "00123,2024,5,Monday,09:30,N/A,£2.50,020 7946 0958\n"
        "00456,2023,8.5,Tuesday,10:00,null,£3.00,07946 201234\n"
    )
    write_csv(inputs / "staff.csv", original)

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "staff_cleaned.csv")
    expected = pd.read_csv(inputs / "staff.csv", dtype=str, keep_default_na=False)
    pd.testing.assert_frame_equal(cleaned, expected)


def test_real_excel_dates_are_standardized(workspace):
    inputs = setup_input(workspace)
    pd.DataFrame(
        {
            "Invoice": ["INV-1", "INV-2"],
            "Paid On": [datetime(2024, 1, 15), datetime(2024, 3, 2)],
            "Amount": [120.5, 99],
        }
    ).to_excel(inputs / "invoices.xlsx", index=False)

    excel_cleaner.main()

    cleaned = pd.read_excel(workspace / "cleaned_spreadsheets" / "invoices_cleaned.xlsx")
    assert cleaned["Paid On"].tolist() == ["2024-01-15", "2024-03-02"]
    assert cleaned["Amount"].tolist() == [120.5, 99]


def test_every_sheet_in_a_workbook_is_kept(workspace, capsys):
    inputs = setup_input(workspace)
    with pd.ExcelWriter(inputs / "report.xlsx") as writer:
        pd.DataFrame({"Region": ["North", "North", "South"]}).to_excel(
            writer, sheet_name="Sales", index=False
        )
        pd.DataFrame({"Name": ["Ada"]}).to_excel(writer, sheet_name="Team", index=False)

    excel_cleaner.main()

    sheets = pd.read_excel(
        workspace / "cleaned_spreadsheets" / "report_cleaned.xlsx", sheet_name=None
    )
    assert list(sheets) == ["Sales", "Team"]
    assert sheets["Sales"]["Region"].tolist() == ["North", "South"]
    assert sheets["Team"]["Name"].tolist() == ["Ada"]
    assert "This workbook has 2 sheets" in capsys.readouterr().out


def test_windows_csv_with_pound_sign_opens(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "prices.csv", "Item,Price\nTea,£2.50\nCafé,£3.10\n", encoding="cp1252")

    excel_cleaner.main()

    cleaned = read_cleaned_csv(workspace, "prices_cleaned.csv")
    assert cleaned["Price"].tolist() == ["£2.50", "£3.10"]
    assert cleaned["Item"].tolist() == ["Tea", "Café"]


def test_output_names_and_originals_untouched(workspace):
    inputs = setup_input(workspace)
    csv_file = write_csv(inputs / "data.csv", "A\n1\n1\n")
    pd.DataFrame({"A": [1, 1]}).to_excel(inputs / "book.xlsx", index=False)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}

    excel_cleaner.main()

    outputs = sorted(p.name for p in (workspace / "cleaned_spreadsheets").iterdir())
    assert outputs == ["book_cleaned.xlsx", "data_cleaned.csv"]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    assert after == before
    assert csv_file.read_text() == "A\n1\n1\n"


def test_excel_lock_files_and_other_files_are_ignored(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(inputs / "real.csv", "A\n1\n")
    (inputs / "~$real.xlsx").write_bytes(b"Excel lock file")
    (inputs / "notes.txt").write_text("not a spreadsheet")

    excel_cleaner.main()

    assert "Found 1 spreadsheet(s)" in capsys.readouterr().out


def test_creates_input_folder_and_explains_next_steps(workspace, capsys):
    excel_cleaner.main()

    assert (workspace / "input_spreadsheets").is_dir()
    assert (workspace / "cleaned_spreadsheets").is_dir()
    assert "No Excel or CSV files found yet." in capsys.readouterr().out


def test_broken_file_is_skipped_and_others_still_work(workspace, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.xlsx").write_bytes(b"this is not really excel")
    write_csv(inputs / "b_good.csv", "A\n1\n")

    excel_cleaner.main()

    assert "Could not open this file" in capsys.readouterr().out
    assert (workspace / "cleaned_spreadsheets" / "b_good_cleaned.csv").exists()


def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "terminal.csv", "Date\n01/15/2024\n01/15/2024\n")

    result = run_script("excel_cleaner.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "All done!" in result.stdout
    cleaned = read_cleaned_csv(workspace, "terminal_cleaned.csv")
    assert cleaned["Date"].tolist() == ["2024-01-15"]

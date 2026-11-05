"""Tests for spreadsheet_merger.py."""

import csv
import hashlib
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

import spreadsheet_merger
from conftest import run_script


def setup_input(workspace):
    folder = workspace / "spreadsheets_to_merge"
    folder.mkdir()
    return folder


def write_csv(path, text, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))
    return path


def merged_files(workspace, suffix=".xlsx"):
    return sorted((workspace / "merged_spreadsheets").glob(f"*{suffix}"))


def read_merged(workspace):
    """Return (header list, list of row dicts) from the one merged .xlsx file."""
    files = merged_files(workspace)
    assert len(files) == 1, files
    sheet = load_workbook(files[0]).active
    rows = list(sheet.iter_rows(values_only=True))
    headers = list(rows[0])
    return headers, [dict(zip(headers, row)) for row in rows[1:]]


def test_csv_and_excel_files_are_combined_with_source_columns(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(inputs / "east.csv", "Order ID,Amount\nE1,10\nE2,20\n")
    pd.DataFrame({"Order ID": ["N1"], "Amount": [30]}).to_excel(
        inputs / "north.xlsx", sheet_name="March", index=False
    )

    spreadsheet_merger.main()

    headers, rows = read_merged(workspace)
    assert headers == ["Source file", "Source sheet", "Order ID", "Amount"]
    assert [(r["Source file"], r["Source sheet"], r["Order ID"]) for r in rows] == [
        ("east.csv", None, "E1"),
        ("east.csv", None, "E2"),
        ("north.xlsx", "March", "N1"),
    ]
    out = capsys.readouterr().out
    assert "Rows merged:    3" in out
    assert "Every file has the same columns" in out


def test_every_sheet_of_a_workbook_is_merged(workspace, capsys):
    inputs = setup_input(workspace)
    with pd.ExcelWriter(inputs / "branches.xlsx") as writer:
        pd.DataFrame({"Item": ["Tea"]}).to_excel(writer, sheet_name="Jan", index=False)
        pd.DataFrame({"Item": ["Cake", "Juice"]}).to_excel(writer, sheet_name="Feb", index=False)

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [(r["Source sheet"], r["Item"]) for r in rows] == [
        ("Jan", "Tea"),
        ("Feb", "Cake"),
        ("Feb", "Juice"),
    ]
    assert "This workbook has 2 sheets" in capsys.readouterr().out


def test_first_sheet_only_setting(workspace, monkeypatch):
    monkeypatch.setattr(spreadsheet_merger, "USE_ONLY_FIRST_SHEET", True)
    inputs = setup_input(workspace)
    with pd.ExcelWriter(inputs / "report.xlsx") as writer:
        pd.DataFrame({"Item": ["Tea"]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame({"Note": ["ignore me"]}).to_excel(writer, sheet_name="Notes", index=False)

    spreadsheet_merger.main()

    headers, rows = read_merged(workspace)
    assert "Note" not in headers
    assert [(r["Source sheet"], r["Item"]) for r in rows] == [("Sales", "Tea")]


def test_headers_match_ignoring_capitals_and_spaces(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Order Date,Customer Name\n2024-01-05,Ada\n")
    write_csv(inputs / "b.csv", "order date ,CUSTOMER   NAME\n2024-01-06,Bob\n")
    write_csv(inputs / "c.csv", "  ORDER DATE,customer name\n2024-01-07,Cy\n")

    spreadsheet_merger.main()

    headers, rows = read_merged(workspace)
    assert headers == ["Source file", "Source sheet", "Order Date", "Customer Name"]
    assert [r["Customer Name"] for r in rows] == ["Ada", "Bob", "Cy"]
    assert [r["Order Date"] for r in rows] == ["2024-01-05", "2024-01-06", "2024-01-07"]


def test_extra_and_missing_columns_are_added_and_reported(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Item,Amount\nTea,1\n")
    write_csv(inputs / "b.csv", "Item,Discount,Amount\nCake,5%,2\n")
    write_csv(inputs / "c.csv", "Amount,Item\n3,Juice\n")

    spreadsheet_merger.main()

    headers, rows = read_merged(workspace)
    assert headers == ["Source file", "Source sheet", "Item", "Amount", "Discount"]
    assert [(r["Item"], r["Amount"], r["Discount"]) for r in rows] == [
        ("Tea", 1, None),
        ("Cake", 2, "5%"),
        ("Juice", 3, None),
    ]
    out = capsys.readouterr().out
    assert 'Column "Discount" only appears in 1 of 3 files (b.csv).' in out


def test_file_with_no_matching_columns_is_warned_about(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(inputs / "sales_jan.csv", "Item,Amount\nTea,1\n")
    write_csv(inputs / "sales_feb.csv", "Item,Amount\nCake,2\n")
    write_csv(inputs / "staff.csv", "Name,Team\nAda,HR\n")

    spreadsheet_merger.main()

    out = capsys.readouterr().out
    assert "staff.csv has no column titles in common with the other files" in out
    assert "Warnings:       1" in out
    # The normal columns are not reported as missing because of the odd file
    assert 'Column "Item"' not in out
    _, rows = read_merged(workspace)
    assert rows[-1]["Name"] == "Ada"


def test_leading_zeros_and_text_like_na_are_kept(workspace):
    inputs = setup_input(workspace)
    write_csv(
        inputs / "staff.csv",
        "Employee ID,Status,Phone,Price,Code\n"
        "00123,N/A,020 7946 0958,£2.50,0042\n"
        "00456,null,07946 201234,£3.00,17\n",
    )
    pd.DataFrame({"Employee ID": ["00789"], "Status": ["NA"]}).to_excel(
        inputs / "more.xlsx", index=False
    )

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [r["Employee ID"] for r in rows] == ["00789", "00123", "00456"]
    assert [r["Status"] for r in rows] == ["NA", "N/A", "null"]
    assert rows[1]["Phone"] == "020 7946 0958"
    assert rows[1]["Price"] == "£2.50"
    assert [r["Code"] for r in rows[1:]] == ["0042", "17"]


def test_clearly_numeric_columns_become_real_numbers(workspace):
    inputs = setup_input(workspace)
    write_csv(
        inputs / "sales.csv",
        "Store ID,Amount,Units,Card Number,Mixed\n"
        "101,120.00,3,4929123456781234,7\n"
        "102,75.50,10,4929123456785678,seven\n",
    )

    spreadsheet_merger.main()

    sheet = load_workbook(merged_files(workspace)[0]).active
    headers = [cell.value for cell in sheet[1]]
    second = {h: cell for h, cell in zip(headers, sheet[3])}
    assert second["Amount"].value == 75.5
    assert second["Amount"].number_format == "0.00"
    assert second["Units"].value == 10
    # Kept as text: an ID column, a 16-digit number, and a column with words
    assert second["Store ID"].value == "102"
    assert second["Card Number"].value == "4929123456785678"
    assert second["Mixed"].value == "seven"


def test_numbers_setting_off_keeps_everything_as_text(workspace, monkeypatch):
    monkeypatch.setattr(spreadsheet_merger, "SAVE_NUMBERS_AS_NUMBERS", False)
    inputs = setup_input(workspace)
    write_csv(inputs / "sales.csv", "Amount\n120.00\n")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert rows[0]["Amount"] == "120.00"


def test_excel_values_are_kept_as_shown(workspace):
    inputs = setup_input(workspace)
    pd.DataFrame(
        {
            "Paid On": [datetime(2024, 1, 15), datetime(2024, 3, 2, 14, 30)],
            "Amount": [120.5, 99],
            "Approved": [True, False],
        }
    ).to_excel(inputs / "invoices.xlsx", index=False)

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [r["Paid On"] for r in rows] == ["2024-01-15", "2024-03-02 14:30"]
    assert [r["Amount"] for r in rows] == [120.5, 99]
    assert [r["Approved"] for r in rows] == ["TRUE", "FALSE"]


def test_windows_csv_with_pound_sign_opens(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "prices.csv", "Item,Price\nTea,£2.50\nCafé,£3.10\n", encoding="cp1252")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [r["Price"] for r in rows] == ["£2.50", "£3.10"]
    assert [r["Item"] for r in rows] == ["Tea", "Café"]


def test_semicolon_csv_is_understood(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "europe.csv", "Item;Price\nTea;2,50\n")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert rows == [{"Source file": "europe.csv", "Source sheet": None, "Item": "Tea", "Price": "2,50"}]


def test_repeated_header_rows_and_empty_rows_are_skipped(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(
        inputs / "pasted.csv",
        "\n"
        "Item,Amount\n"
        "Tea,1\n"
        ",\n"
        "\n"
        "item , AMOUNT\n"
        "Cake,2\n"
        "Item,Amount\n"
        "Juice,3\n",
    )

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [r["Item"] for r in rows] == ["Tea", "Cake", "Juice"]
    out = capsys.readouterr().out
    assert "Skipped 3 empty row(s)." in out
    assert "Skipped 2 repeated header row(s)" in out


def test_empty_sheets_and_empty_files_are_skipped(workspace, capsys):
    inputs = setup_input(workspace)
    with pd.ExcelWriter(inputs / "book.xlsx") as writer:
        pd.DataFrame({"Item": ["Tea"]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Blank", index=False)
        pd.DataFrame({"Item": []}).to_excel(writer, sheet_name="Titles only", index=False)
    write_csv(inputs / "empty.csv", "")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [(r["Source sheet"], r["Item"]) for r in rows] == [("Sales", "Tea")]
    out = capsys.readouterr().out
    assert "Sheet 'Blank' is empty — skipped." in out
    assert "Sheet 'Titles only' has column titles but no data rows — skipped." in out
    assert "Skipped this file — it has no data rows." in out
    assert "Files merged:   1 of 2" in out


def test_source_columns_can_be_turned_off(workspace, monkeypatch):
    monkeypatch.setattr(spreadsheet_merger, "ADD_SOURCE_COLUMNS", False)
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Item\nTea\n")

    spreadsheet_merger.main()

    headers, _ = read_merged(workspace)
    assert headers == ["Item"]


def test_duplicates_are_kept_by_default(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Item,Amount\nTea,1\nTea,1\n")
    write_csv(inputs / "b.csv", "Item,Amount\nTea,1\n")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert len(rows) == 3


def test_duplicates_across_files_can_be_removed(workspace, monkeypatch, capsys):
    monkeypatch.setattr(spreadsheet_merger, "REMOVE_DUPLICATES", True)
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Item,Amount\nTea,1\nTea,1\nCake,2\n")
    write_csv(inputs / "b.csv", "item,amount\nTea,1\nTea,2\n")

    spreadsheet_merger.main()

    _, rows = read_merged(workspace)
    assert [(r["Source file"], r["Item"], r["Amount"]) for r in rows] == [
        ("a.csv", "Tea", 1),
        ("a.csv", "Cake", 2),
        ("b.csv", "Tea", 2),
    ]
    assert "Removed 2 completely duplicate row(s)." in capsys.readouterr().out


def test_output_name_and_never_overwrites(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Item\nTea\n")

    spreadsheet_merger.main()
    first = merged_files(workspace)
    assert len(first) == 1
    assert first[0].name.startswith("merged_")
    first_bytes = first[0].read_bytes()

    spreadsheet_merger.main()

    assert len(merged_files(workspace)) == 2
    assert first[0].read_bytes() == first_bytes

    out_dir = workspace / "merged_spreadsheets"
    when = datetime(2024, 3, 15, 9, 30)
    (out_dir / "merged_2024-03-15_0930.xlsx").write_bytes(b"older")
    (out_dir / "merged_2024-03-15_0930_2.csv").write_bytes(b"older")
    assert spreadsheet_merger.output_path_for(out_dir, when).name == "merged_2024-03-15_0930_3.xlsx"


def test_csv_copy_setting(workspace, monkeypatch):
    monkeypatch.setattr(spreadsheet_merger, "ALSO_SAVE_CSV", True)
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "ID,Price\n007,£2\n")

    spreadsheet_merger.main()

    csv_files = merged_files(workspace, ".csv")
    assert len(csv_files) == 1
    assert csv_files[0].stem == merged_files(workspace)[0].stem
    with open(csv_files[0], encoding="utf-8-sig", newline="") as f:
        assert list(csv.reader(f)) == [
            ["Source file", "Source sheet", "ID", "Price"],
            ["a.csv", "", "007", "£2"],
        ]


def test_excel_output_is_formatted(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "a.csv", "Customer,Note\nAda,=1+1\n")

    spreadsheet_merger.main()

    sheet = load_workbook(merged_files(workspace)[0]).active
    assert sheet.title == "Merged"
    assert sheet.freeze_panes == "A2"
    assert all(cell.font.b for cell in sheet[1])
    assert sheet.auto_filter.ref == "A1:D2"
    assert sheet.column_dimensions["A"].width >= len("Source file")
    # Text that starts with "=" stays text instead of becoming a formula
    assert sheet["D2"].value == "=1+1"
    assert sheet["D2"].data_type == "s"


def test_excel_lock_files_and_other_files_are_ignored(workspace, capsys):
    inputs = setup_input(workspace)
    write_csv(inputs / "real.csv", "A\n1\n")
    (inputs / "~$real.xlsx").write_bytes(b"Excel lock file")
    (inputs / "notes.txt").write_text("not a spreadsheet")

    spreadsheet_merger.main()

    assert "Found 1 spreadsheet(s)" in capsys.readouterr().out


def test_broken_file_is_skipped_and_others_still_work(workspace, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.xlsx").write_bytes(b"this is not really excel")
    write_csv(inputs / "b_good.csv", "A\n1\n")

    spreadsheet_merger.main()

    out = capsys.readouterr().out
    assert "Skipped this file — it could not be opened" in out
    assert "Files merged:   1 of 2" in out
    _, rows = read_merged(workspace)
    assert rows[0]["Source file"] == "b_good.csv"


def test_creates_input_folder_and_explains_next_steps(workspace, capsys):
    spreadsheet_merger.main()

    assert (workspace / "spreadsheets_to_merge").is_dir()
    assert (workspace / "merged_spreadsheets").is_dir()
    out = capsys.readouterr().out
    assert "Created folder" in out
    assert "What to do next" in out
    assert merged_files(workspace) == []


def test_originals_are_untouched(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "data.csv", "A\n1\n\nA\n1\n")
    pd.DataFrame({"A": [1, 1]}).to_excel(inputs / "book.xlsx", index=False)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}

    spreadsheet_merger.main()

    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    assert after == before


def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    write_csv(inputs / "branch_a.csv", "Order ID,Amount\n001,10\n")
    write_csv(inputs / "branch_b.csv", "order id,amount,Region\n002,20,North\n")

    result = run_script("spreadsheet_merger.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "All done!" in result.stdout
    assert 'Column "Region" only appears in 1 of 2 files (branch_b.csv).' in result.stdout
    _, rows = read_merged(workspace)
    assert [(r["Order ID"], r["Amount"], r["Region"]) for r in rows] == [
        ("001", 10, None),
        ("002", 20, "North"),
    ]

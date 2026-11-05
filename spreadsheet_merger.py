#!/usr/bin/env python3
"""
Spreadsheet Merger
==================
This script looks in a "spreadsheets_to_merge" folder for Excel (.xlsx / .xls)
or CSV (.csv) files — for example the monthly report from each branch — and
combines all of them into ONE spreadsheet. Along the way it:

  1. Matches columns by their title, ignoring capitals and extra spaces
     ("Order Date" and "order date " count as the same column)
  2. Adds columns that only some files have (blank for the other files) and
     tells you exactly which columns those are
  3. Adds "Source file" and "Source sheet" columns so you can always see
     where each row came from
  4. Skips empty rows, empty sheets, and header rows that were pasted again
     in the middle of the data
  5. Saves the result as merged_YYYY-MM-DD_HHMM.xlsx in "merged_spreadsheets"

Values are kept exactly as typed: ID numbers keep their leading zeros and
text like "N/A" stays as it is. Every sheet of every workbook is included.

Your original files are never changed, and an earlier merged file is never
overwritten.

How to run (after following README.md):
    python spreadsheet_merger.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus pandas / openpyxl for spreadsheet work
# ---------------------------------------------------------------------------

import csv  # Reads and writes CSV files (plain-text spreadsheets)
import io  # Lets the CSV reader work on text we have already loaded
import math  # Used to spot "not a number" values from Excel
import re  # "Regular expressions" — a way to spot text patterns like numbers
import sys  # Gives access to the terminal output settings
from datetime import date, datetime, time  # To recognise dates and times
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import Dict, List, Optional, Tuple

# pandas = reads Excel files (both .xlsx and the older .xls)
# openpyxl = writes the merged .xlsx file with a bold, frozen header row
try:
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The spreadsheet libraries are not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install -r requirements.txt")
    print()
    print("Or install just the spreadsheet tools:")
    print()
    print("    pip install pandas openpyxl xlrd")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the Excel / CSV files to combine
INPUT_FOLDER_NAME = "spreadsheets_to_merge"

# Folder where THIS SCRIPT saves the merged spreadsheet
OUTPUT_FOLDER_NAME = "merged_spreadsheets"

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# True  = use only the FIRST sheet of each Excel workbook (handy when every
#         workbook has extra sheets like "Notes" or "Summary" you don't want)
# False = use every sheet of every workbook
USE_ONLY_FIRST_SHEET = False

# True = add "Source file" and "Source sheet" columns at the front, so you
#        can always trace a row back to where it came from
ADD_SOURCE_COLUMNS = True

# True = also save a .csv copy of the merged table next to the .xlsx file
ALSO_SAVE_CSV = False

# True = remove rows that are 100% identical to an earlier row, even if they
#        came from different files (the "Source file" columns are ignored
#        when comparing).
# It is OFF by default because two identical rows are often real data —
# for example two customers buying the same item on the same day. Turn it
# on only if you know your files overlap (like the same report saved twice).
REMOVE_DUPLICATES = False

# True = in the Excel file, columns where EVERY value is a plain number
#        (like 120 or 75.50) are saved as real numbers, so SUM and sorting
#        work straight away. Anything that could be an ID stays as text:
#        values with leading zeros (00123), very long numbers (card numbers,
#        barcodes), and columns whose title suggests an ID or code.
# False = keep every value as text, exactly as typed.
# (The optional CSV copy is always plain text either way.)
SAVE_NUMBERS_AS_NUMBERS = True

# Words in a column title that mean "this looks like a number, but it's
# really an ID — keep it as text"
TEXT_COLUMN_WORDS = (
    "id",
    "code",
    "phone",
    "mobile",
    "tel",
    "zip",
    "postcode",
    "postal",
    "sku",
    "barcode",
    "ean",
    "upc",
    "pin",
)

# Numbers with more digits than this are treated as IDs, not amounts
# (Excel shows 12+ digit numbers in scientific notation, like 1.23E+11)
MAX_NUMBER_DIGITS = 11

# Text encodings to try when opening a CSV, in order.
# Excel on Windows often saves CSVs as "cp1252" rather than "utf-8",
# which is why a "£" sign can stop a CSV from opening.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

# Column separators we recognise in CSV files. Excel in many European
# countries saves CSVs with ";" instead of ",".
CSV_SEPARATORS = (",", ";", "\t")

# Widest a column is allowed to be in the merged Excel file (in characters)
MAX_COLUMN_WIDTH = 50

# The most rows one Excel sheet can hold (a limit set by Excel itself)
EXCEL_MAX_ROWS = 1_048_576

# Names of the two extra columns added at the front
SOURCE_FILE_COLUMN = "Source file"
SOURCE_SHEET_COLUMN = "Source sheet"

# A "plain number": optional minus sign, no leading zeros (so 00123 is not
# a number), optional decimal part. Examples: 0, 42, -7, 120.5, 0.25
PLAIN_NUMBER_PATTERN = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?$")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class SheetData:
    """One sheet (or one CSV file) after reading: its columns and its rows."""

    def __init__(self, file_name: str, sheet_name: str) -> None:
        self.file_name = file_name
        self.sheet_name = sheet_name  # Blank for CSV files
        self.headers: List[str] = []  # Column titles, tidied up
        self.keys: List[str] = []  # Lower-case versions used for matching
        self.rows: List[List[str]] = []  # Every data row, as text


def ensure_folders() -> Tuple[Path, Path]:
    """
    Make sure the input and output folders exist.
    Returns (input_path, output_path).
    """
    project_root = Path(".")

    input_dir = project_root / INPUT_FOLDER_NAME
    output_dir = project_root / OUTPUT_FOLDER_NAME

    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {input_dir.resolve()}")
        print("   → Put the .xlsx, .xls, or .csv files to combine in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_spreadsheets(input_dir: Path) -> List[Path]:
    """Return a sorted list of Excel/CSV files in the input folder (not subfolders)."""
    files = []
    for item in input_dir.iterdir():
        # Skip hidden files and the temporary "~$report.xlsx" lock files
        # Excel creates while a workbook is open — they are not real data.
        if item.name.startswith((".", "~$")):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append(item)

    return sorted(files, key=lambda p: p.name.lower())


def cell_to_text(value: object) -> str:
    """
    Turn one cell from Excel into text, the way Excel would show it.

    We work with text everywhere so nothing changes by accident:
      - empty cells           → ""  (blank)
      - 5 or 5.0              → "5"
      - 120.5                 → "120.5"
      - TRUE / FALSE          → "TRUE" / "FALSE"
      - a date at midnight    → "2024-01-15"
      - a date with a time    → "2024-01-15 14:30"
      - a time of day         → "09:30"
      - text (like "00123")   → exactly as typed
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # True/False must be checked before numbers (Python counts True as 1)
    if pd.api.types.is_bool(value):
        return "TRUE" if value else "FALSE"
    if pd.api.types.is_integer(value):
        return str(int(value))
    if pd.api.types.is_float(value):
        number = float(value)
        if math.isnan(number):
            return ""  # An empty cell
        if number.is_integer() and abs(number) < 1e15:
            return str(int(number))
        # 15 significant digits = the same precision Excel shows
        return format(number, ".15g")
    if isinstance(value, datetime):  # Also covers pandas "Timestamp"
        if pd.isna(value):
            return ""
        if (value.hour, value.minute, value.second) == (0, 0, 0):
            return value.strftime("%Y-%m-%d")
        if value.second == 0:
            return value.strftime("%Y-%m-%d %H:%M")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M" if value.second == 0 else "%H:%M:%S")
    return str(value)


def guess_csv_separator(text: str) -> str:
    """
    Work out which character separates the columns in a CSV file.

    We look at the first line with something on it (normally the headers)
    and pick whichever separator appears most often. Comma wins a tie.
    """
    for line in text.splitlines():
        if line.strip():
            counts = {sep: line.count(sep) for sep in CSV_SEPARATORS}
            best = max(CSV_SEPARATORS, key=lambda sep: counts[sep])
            return best if counts[best] > 0 else ","
    return ","


def read_csv_any_encoding(path: Path) -> List[List[str]]:
    """
    Read a CSV file into rows of text, trying a few common text encodings
    until one works.

    Python's built-in csv reader keeps every cell as text, exactly as typed:
    employee ID 00123 keeps its leading zeros, and text like "N/A", "NA" or
    "null" stays as it is instead of being turned into a blank. It also
    copes with rows that have more or fewer cells than the header row.
    """
    raw = path.read_bytes()
    last_error = None
    for encoding in CSV_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError as err:
            last_error = err  # Wrong encoding — try the next one
    else:
        raise last_error

    separator = guess_csv_separator(text)
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=separator)]


def read_spreadsheet(path: Path) -> Dict[str, List[List[str]]]:
    """
    Load a spreadsheet into memory as {sheet name: rows of text}.

    - CSV files have just one table (its sheet name is left blank).
    - Excel files can have several sheets; we read all of them
      (or only the first one, if USE_ONLY_FIRST_SHEET is True).
    """
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return {"": read_csv_any_encoding(path)}

    if suffix in {".xlsx", ".xls"}:
        try:
            book = pd.ExcelFile(path)
        except ImportError as err:
            library = "xlrd" if suffix == ".xls" else "openpyxl"
            raise RuntimeError(
                f"Reading {suffix} files needs the '{library}' library. "
                f"Run:  pip install {library}"
            ) from err

        sheets = {}
        # "with" makes sure the file is closed again when we are finished
        with book:
            names = book.sheet_names[:1] if USE_ONLY_FIRST_SHEET else book.sheet_names
            for name in names:
                # header=None  = treat the header row like any other row, so we
                #                can tidy it up and spot repeats ourselves
                # dtype=object = hand us each cell exactly as stored in Excel
                table = book.parse(
                    name,
                    header=None,
                    dtype=object,
                    keep_default_na=False,
                    na_values=[""],
                )
                sheets[str(name)] = [[cell_to_text(cell) for cell in row] for row in table.values.tolist()]
        return sheets

    raise ValueError(f"Unsupported file type: {suffix}")


def tidy_header(text: str) -> str:
    """Remove extra spaces from a column title: '  Order   Date ' → 'Order Date'."""
    return " ".join(text.split())


def matching_key(text: str) -> str:
    """
    The version of a column title we use to MATCH columns between files.
    Capitals and extra spaces are ignored, so 'Order Date', 'ORDER DATE'
    and ' order  date ' all give the same key: 'order date'.
    """
    return tidy_header(text).casefold()


def row_is_empty(row: List[str]) -> bool:
    """True if every cell in the row is blank (or only spaces)."""
    return all(not cell.strip() for cell in row)


def build_sheet(file_name: str, sheet_name: str, raw_rows: List[List[str]], indent: str) -> Optional[SheetData]:
    """
    Turn the raw rows of one sheet into a tidy SheetData:
      - the first non-empty row becomes the column titles
      - empty rows and repeated header rows are skipped
      - columns without a title get one (if they contain data)

    Returns None if the sheet has no data rows at all.
    """
    label = f"Sheet '{sheet_name}'" if sheet_name else "This file"

    # Drop empty rows (anywhere: at the top, in the middle, at the end)
    non_empty = [row for row in raw_rows if not row_is_empty(row)]
    empty_rows = sum(1 for row in raw_rows if row_is_empty(row))
    if not non_empty:
        print(f"{indent}{label} is empty — skipped.")
        return None

    # Every row gets the same number of cells, so columns line up
    width = max(len(row) for row in non_empty)
    non_empty = [row + [""] * (width - len(row)) for row in non_empty]
    header_row, data_rows = non_empty[0], non_empty[1:]

    # Header rows that appear AGAIN further down (common when blocks of data
    # were copied and pasted together) are not real data — skip them.
    header_keys = [matching_key(cell) for cell in header_row]
    repeated_headers = sum(1 for row in data_rows if [matching_key(c) for c in row] == header_keys)
    data_rows = [row for row in data_rows if [matching_key(c) for c in row] != header_keys]

    if empty_rows:
        print(f"{indent}Skipped {empty_rows} empty row(s).")
    if repeated_headers:
        print(f"{indent}Skipped {repeated_headers} repeated header row(s) found inside the data.")

    if not data_rows:
        print(f"{indent}{label} has column titles but no data rows — skipped.")
        return None

    sheet = SheetData(file_name, sheet_name)
    keep_columns = []
    for position, title in enumerate(header_row):
        title = tidy_header(title)
        has_data = any(row[position].strip() for row in data_rows)
        if not title:
            if not has_data:
                continue  # A completely empty column — leave it out
            title = f"Column {position + 1}"
            print(f'{indent}Note: column {position + 1} has no title, so it is called "{title}".')

        # The same title twice in one sheet? Number the second one.
        key = matching_key(title)
        if key in sheet.keys:
            count = 2
            while matching_key(f"{title} ({count})") in sheet.keys:
                count += 1
            print(f'{indent}Note: the column "{title}" appears more than once — '
                  f'the extra one is called "{title} ({count})".')
            title = f"{title} ({count})"
            key = matching_key(title)

        sheet.headers.append(title)
        sheet.keys.append(key)
        keep_columns.append(position)

    sheet.rows = [[row[position] for position in keep_columns] for row in data_rows]
    print(f"{indent}{label}: {len(sheet.rows)} row(s), {len(sheet.headers)} column(s).")
    return sheet


def read_one_file(source: Path, index: int, total: int) -> Tuple[List[SheetData], Optional[str]]:
    """
    Read one spreadsheet and tidy every sheet in it, with friendly messages.

    Returns (list of sheets with data, warning text or None).
    """
    print(f"Reading file {index} of {total}: {source.name} ...")

    try:
        raw_sheets = read_spreadsheet(source)
    except Exception as err:
        print(f"   ⚠️  Skipped this file — it could not be opened. Reason: {err}")
        print()
        return [], f"{source.name}: could not be opened ({err})"

    try:
        indent = "   "
        if len(raw_sheets) > 1:
            print(f"   This workbook has {len(raw_sheets)} sheets — reading each one.")
        sheets = []
        for sheet_name, raw_rows in raw_sheets.items():
            sheet = build_sheet(source.name, sheet_name, raw_rows, indent)
            if sheet is not None:
                sheets.append(sheet)
    except Exception as err:
        print(f"   ⚠️  Skipped this file — something went wrong while reading it. Reason: {err}")
        print()
        return [], f"{source.name}: could not be read ({err})"

    if not sheets:
        print("   ⚠️  Skipped this file — it has no data rows.")
        print()
        return [], f"{source.name}: has no data rows"

    rows = sum(len(sheet.rows) for sheet in sheets)
    print(f"   Done! {rows} row(s) ready to merge.")
    print()
    return sheets, None


def merge_sheets(sheets: List[SheetData]) -> Tuple[List[str], List[List[str]]]:
    """
    Stack every sheet into one big table, lining columns up by title.

    Columns keep the spelling and order in which they were FIRST seen.
    A column that only some files have is added at the end, and rows from
    the other files simply get a blank cell there.

    Returns (column titles, rows).
    """
    titles: Dict[str, str] = {}  # matching key → title as first spelled
    reserved = {matching_key(SOURCE_FILE_COLUMN), matching_key(SOURCE_SHEET_COLUMN)}

    # Step 1: collect every column title, in first-seen order
    for sheet in sheets:
        for position, key in enumerate(sheet.keys):
            if ADD_SOURCE_COLUMNS and key in reserved:
                # The file already has a "Source file" column (for example an
                # earlier merged file) — keep it, under a slightly different name
                sheet.headers[position] += " (original)"
                key = sheet.keys[position] = matching_key(sheet.headers[position])
            titles.setdefault(key, sheet.headers[position])

    column_order = list(titles)  # Keys in first-seen order
    where = {key: position for position, key in enumerate(column_order)}

    # Step 2: copy each row into the right columns of the big table
    merged_rows = []
    for sheet in sheets:
        targets = [where[key] for key in sheet.keys]
        for row in sheet.rows:
            new_row = [""] * len(column_order)
            for value, target in zip(row, targets):
                new_row[target] = value
            if ADD_SOURCE_COLUMNS:
                new_row = [sheet.file_name, sheet.sheet_name] + new_row
            merged_rows.append(new_row)

    headers = [titles[key] for key in column_order]
    if ADD_SOURCE_COLUMNS:
        headers = [SOURCE_FILE_COLUMN, SOURCE_SHEET_COLUMN] + headers
    return headers, merged_rows


def remove_duplicate_rows(rows: List[List[str]]) -> Tuple[List[List[str]], int]:
    """
    Drop rows that are 100% identical to an earlier row.
    The Source file / Source sheet columns are ignored when comparing, so
    the same row in two different files counts as a duplicate.

    Returns (rows that remain, how many were removed).
    """
    skip = 2 if ADD_SOURCE_COLUMNS else 0
    seen = set()
    kept = []
    for row in rows:
        fingerprint = tuple(row[skip:])
        if fingerprint in seen:
            continue  # The first copy stays; later copies are removed
        seen.add(fingerprint)
        kept.append(row)
    return kept, len(rows) - len(kept)


def report_partial_columns(headers: List[str], sheets: List[SheetData]) -> List[str]:
    """
    Print which columns are missing from some files. Returns those lines.

    Only the sheets passed in are counted (sheets that look like a different
    kind of report get their own warning instead, so they are left out here).
    """
    file_count = len({sheet.file_name for sheet in sheets})
    lines = []
    for title in headers:
        key = matching_key(title)
        files = {sheet.file_name for sheet in sheets if key in sheet.keys}
        if files and len(files) < file_count:
            line = f'Column "{title}" only appears in {len(files)} of {file_count} files'
            if len(files) <= 3:
                line += f" ({', '.join(sorted(files, key=str.lower))})"
            lines.append(line + ".")

    if lines:
        print("Some columns are not in every file (the other rows are left blank there):")
        for line in lines:
            print(f"   • {line}")
    else:
        print("Every file has the same columns. Nice!")
    print()
    return lines


def find_unmatched_sheets(sheets: List[SheetData]) -> List[SheetData]:
    """
    Find sheets that share NO column titles with any other sheet. They are
    probably a different kind of report (for example a staff list mixed in
    with sales reports). Their rows are still merged, in their own columns.
    """
    if len(sheets) < 2:
        return []
    unmatched = []
    for sheet in sheets:
        other_keys = set()
        for other in sheets:
            if other is not sheet:
                other_keys.update(other.keys)
        if not other_keys.intersection(sheet.keys):
            unmatched.append(sheet)
    return unmatched


def unmatched_warning(sheet: SheetData) -> str:
    """The warning text for a sheet that matches no other sheet."""
    where = sheet.file_name + (f" (sheet '{sheet.sheet_name}')" if sheet.sheet_name else "")
    return (f"{where} has no column titles in common with the other files — "
            "it may be a different kind of report. Its rows were added in their own columns.")


def output_path_for(output_dir: Path, when: Optional[datetime] = None) -> Path:
    """
    Pick a file name like merged_2024-03-15_0930.xlsx that is not taken yet.

    If that name already exists (two runs in the same minute), we add a
    number instead of overwriting: merged_2024-03-15_0930_2.xlsx
    """
    stem = f"merged_{(when or datetime.now()).strftime('%Y-%m-%d_%H%M')}"
    candidate, count = stem, 2
    # Check the .csv name too, so the Excel file and CSV copy always match
    while (output_dir / f"{candidate}.xlsx").exists() or (output_dir / f"{candidate}.csv").exists():
        candidate = f"{stem}_{count}"
        count += 1
    return output_dir / f"{candidate}.xlsx"


def number_column_style(title: str, values: List[str]) -> Optional[str]:
    """
    Decide whether a column should be saved as real numbers in Excel.

    Returns None to keep the column as text, or an Excel number format:
      "General" for whole numbers, "0.00" (etc.) for decimal amounts so
      75.50 still shows as 75.50 and not 75.5.

    We only convert when it is clearly safe: EVERY filled-in value must be a
    plain number with no leading zeros and not too many digits, and the
    title must not suggest an ID or code.
    """
    words = re.findall(r"[a-z]+", title.casefold())
    if any(word in TEXT_COLUMN_WORDS for word in words):
        return None

    decimals = 0
    filled = 0
    for value in values:
        value = value.strip()
        if not value:
            continue
        filled += 1
        if not PLAIN_NUMBER_PATTERN.match(value):
            return None
        whole, _, fraction = value.lstrip("-").partition(".")
        if len(whole) > MAX_NUMBER_DIGITS or len(whole + fraction) > 15:
            return None  # Probably an ID, or more precision than Excel keeps
        decimals = max(decimals, len(fraction))

    if filled == 0:
        return None
    return "0." + "0" * decimals if decimals else "General"


def column_width(title: str, values: List[str]) -> float:
    """A sensible column width: wide enough for the title and most values."""
    sample = values[:1000]  # Looking at the first 1000 rows is plenty
    longest = max([len(title) + 2] + [len(v) for v in sample])  # +2 for bold
    return min(max(longest + 2, 8), MAX_COLUMN_WIDTH)


def save_excel(headers: List[str], rows: List[List[str]], destination: Path) -> List[str]:
    """
    Write the merged table as a friendly Excel file: bold header row,
    frozen top row, filter buttons, and sensible column widths.

    Returns the titles of the columns saved as real numbers.
    """
    skip = 2 if ADD_SOURCE_COLUMNS else 0
    columns = list(zip(*rows)) if rows else [()] * len(headers)

    # Work out, column by column, whether to save real numbers
    styles: List[Optional[str]] = []
    for position, title in enumerate(headers):
        if SAVE_NUMBERS_AS_NUMBERS and position >= skip:
            styles.append(number_column_style(title, list(columns[position])))
        else:
            styles.append(None)

    # write_only=True streams rows straight to disk, so even very big
    # merges don't use much memory
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Merged")
    sheet.freeze_panes = "A2"  # The header row stays visible when scrolling
    last_cell = f"{get_column_letter(len(headers))}{len(rows) + 1}"
    sheet.auto_filter.ref = f"A1:{last_cell}"  # Filter buttons on the header
    for position, title in enumerate(headers):
        letter = get_column_letter(position + 1)
        sheet.column_dimensions[letter].width = column_width(title, list(columns[position]))

    bold = Font(bold=True)
    header_cells = []
    for title in headers:
        cell = WriteOnlyCell(sheet, value=title)
        cell.font = bold
        header_cells.append(cell)
    sheet.append(header_cells)

    for row in rows:
        cells = []
        for value, style in zip(row, styles):
            if not value:
                cells.append(None)  # A blank cell
                continue
            if style is not None:
                number = float(value) if "." in value else int(value)
                cell = WriteOnlyCell(sheet, value=number)
                cell.number_format = style
            else:
                # Remove invisible control characters Excel can't store
                cell = WriteOnlyCell(sheet, value=ILLEGAL_CHARACTERS_RE.sub("", value))
                # Text starting with "=" must stay text, not become a formula
                cell.data_type = "s"
            cells.append(cell)
        sheet.append(cells)

    try:
        workbook.save(destination)
    except Exception:
        # Don't leave a half-written file behind
        if destination.exists():
            destination.unlink()
        raise

    return [title for title, style in zip(headers, styles) if style is not None]


def save_csv(headers: List[str], rows: List[List[str]], destination: Path) -> None:
    """Write the merged table as a CSV file, every value exactly as text."""
    # utf-8-sig lets Excel open the file with symbols like £ and é intact.
    # newline="" stops blank lines appearing between rows on Windows.
    with open(destination, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main program — runs when you type: python spreadsheet_merger.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Spreadsheet Merger")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    files = find_spreadsheets(input_dir)

    if not files:
        print("No Excel or CSV files found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag the .xlsx / .xls / .csv files you want to combine into it.")
        print("  3. Run this script again:")
        print()
        print("         python spreadsheet_merger.py")
        print()
        return

    total = len(files)
    print(f"Found {total} spreadsheet(s) to merge. Starting now...")
    print()

    # 1) Read every file, one at a time
    all_sheets: List[SheetData] = []
    warnings: List[str] = []
    for i, path in enumerate(files, start=1):
        sheets, warning = read_one_file(path, i, total)
        all_sheets.extend(sheets)
        if warning:
            warnings.append(warning)

    if not all_sheets:
        print("=" * 60)
        print("Nothing to merge — none of the files had any data rows.")
        print("Check that your files have a row of column titles and some data.")
        print("=" * 60)
        print()
        return

    # 2) Line up the columns and stack all the rows together
    print("Combining everything into one table...")
    print("(Columns are matched by title — capitals and extra spaces are ignored.)")
    print()
    headers, rows = merge_sheets(all_sheets)
    merged_files = len({sheet.file_name for sheet in all_sheets})
    unmatched = find_unmatched_sheets(all_sheets)
    report_partial_columns(headers, [s for s in all_sheets if s not in unmatched])

    for sheet in unmatched:
        warning = unmatched_warning(sheet)
        print(f"⚠️  {warning}")
        print()
        warnings.append(warning)

    # 3) Optionally remove rows that appear more than once
    if REMOVE_DUPLICATES:
        rows, removed = remove_duplicate_rows(rows)
        if removed:
            print(f"Removed {removed} completely duplicate row(s).")
        else:
            print("No completely duplicate rows found. Nice!")
        print()

    # 4) Save the result under a brand-new name
    print("Saving the merged spreadsheet...")
    destination = output_path_for(output_dir)
    save_as_excel = len(rows) + 1 <= EXCEL_MAX_ROWS
    try:
        if save_as_excel:
            number_columns = save_excel(headers, rows, destination)
            print(f"   Done! Saved as: {destination.name}")
            if number_columns:
                print(f"   Saved as real numbers (so SUM works): {', '.join(number_columns)}")
        else:
            warning = (f"{len(rows):,} rows is more than one Excel sheet can hold, "
                       "so the merged table was saved as CSV only.")
            print(f"   ⚠️  {warning}")
            warnings.append(warning)
        if ALSO_SAVE_CSV or not save_as_excel:
            csv_destination = destination.with_suffix(".csv")
            save_csv(headers, rows, csv_destination)
            print(f"   Done! Saved as: {csv_destination.name}")
    except Exception as err:
        print(f"   ⚠️  Could not save the merged file. Reason: {err}")
        print("   Check there is free disk space and that you can save into "
              f"'{OUTPUT_FOLDER_NAME}', then run again.")
        print()
        raise SystemExit(1)
    print()

    # 5) Final summary
    data_columns = len(headers) - (2 if ADD_SOURCE_COLUMNS else 0)
    print("=" * 60)
    print("Summary")
    print(f"   Files merged:   {merged_files} of {total}")
    print(f"   Sheets merged:  {len(all_sheets)}")
    print(f"   Rows merged:    {len(rows)}")
    if ADD_SOURCE_COLUMNS:
        print(f"   Columns:        {data_columns} (plus '{SOURCE_FILE_COLUMN}' and '{SOURCE_SHEET_COLUMN}')")
    else:
        print(f"   Columns:        {data_columns}")
    print(f"   Warnings:       {len(warnings)}")
    for warning in warnings:
        print(f"   ⚠️  {warning}")
    print("=" * 60)
    print(f"All done! Check the '{OUTPUT_FOLDER_NAME}' folder for your merged file.")
    print(f"Originals in '{INPUT_FOLDER_NAME}' were left untouched.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

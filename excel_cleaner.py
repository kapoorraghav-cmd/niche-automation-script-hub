#!/usr/bin/env python3
"""
Spreadsheet Cleaner
===================
This script looks in an "input_spreadsheets" folder for Excel (.xlsx / .xls)
or CSV (.csv) files, then for each file it:

  1. Removes completely duplicate rows (every column the same)
  2. Fixes inconsistent date values to a standard YYYY-MM-DD format
  3. Saves a new file with a "_cleaned" suffix into "cleaned_spreadsheets"

Everything else is kept exactly as it was: ID numbers keep their leading
zeros, text like "N/A" stays as typed, and every sheet in a workbook is kept.

Your original files are never changed.

How to run (after following README.md):
    python excel_cleaner.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus pandas / openpyxl for spreadsheet work
# ---------------------------------------------------------------------------

import re  # "Regular expressions" — a way to spot text patterns like years
import sys  # Gives access to the terminal output settings
from pathlib import Path  # Easy, cross-platform file and folder paths

# pandas = the main library for reading and cleaning tables
# openpyxl = needed so pandas can read/write modern Excel .xlsx files
try:
    import pandas as pd
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The pandas library is not installed yet.")
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

# Folder where YOU put the original Excel / CSV files
INPUT_FOLDER_NAME = "input_spreadsheets"

# Folder where THIS SCRIPT saves the cleaned copies
OUTPUT_FOLDER_NAME = "cleaned_spreadsheets"

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# If at least this fraction of filled-in values in a column look like dates,
# we treat the whole column as a date column (when the column name does not
# already hint that it is a date).
DATE_PARSE_SUCCESS_RATE = 0.85

# Words in a column title that strongly suggest "this is a date column"
DATE_NAME_HINTS = (
    "date",
    "day",
    "month",
    "year",
    "dob",
    "birthday",
    "birth",
    "timestamp",
    "time",
    "deadline",
    "due",
)

# Text encodings to try when opening a CSV, in order.
# Excel on Windows often saves CSVs as "cp1252" rather than "utf-8",
# which is why a "£" sign can stop a CSV from opening.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

# A value only counts as a date if it clearly shows a year — either four
# digits like 2024, or a short date like 15/01/24. This protects plain
# numbers (2024, 00123), times (09:30) and day names (Monday) from being
# turned into dates by mistake.
FULL_YEAR_PATTERN = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
SHORT_DATE_PATTERN = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2}$")
PLAIN_NUMBER_PATTERN = re.compile(r"^[+-]?\d+([.,]\d+)?$")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def ensure_folders() -> tuple[Path, Path]:
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
        print("   → Put your .xlsx, .xls, or .csv files in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_spreadsheets(input_dir: Path) -> list[Path]:
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


def read_csv_any_encoding(path: Path) -> pd.DataFrame:
    """
    Read a CSV file, trying a few common text encodings until one works.

    dtype=str reads every cell as text, so nothing gets changed by accident
    (for example, employee ID 00123 keeps its leading zeros).

    keep_default_na=False + na_values=[""] means only truly empty cells count
    as blank. Without this, pandas would quietly wipe out text like "N/A",
    "NA", or "null" that people often type on purpose.
    """
    last_error = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(
                path,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
            )
        except UnicodeDecodeError as err:
            last_error = err  # Wrong encoding — try the next one
    raise last_error


def read_spreadsheet(path: Path) -> dict[str, pd.DataFrame]:
    """
    Load a spreadsheet into memory as {sheet name: table}.

    - CSV files have just one table.
    - Excel files can have several sheets; we read all of them.
    """
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return {"CSV": read_csv_any_encoding(path)}

    if suffix in {".xlsx", ".xls"}:
        try:
            # sheet_name=None = "give me every sheet, not just the first one"
            return pd.read_excel(
                path,
                sheet_name=None,
                keep_default_na=False,
                na_values=[""],
            )
        except ImportError as err:
            library = "xlrd" if suffix == ".xls" else "openpyxl"
            raise RuntimeError(
                f"Reading {suffix} files needs the '{library}' library. "
                f"Run:  pip install {library}"
            ) from err

    raise ValueError(f"Unsupported file type: {suffix}")


def cleaned_output_path(source: Path, output_dir: Path) -> Path:
    """
    Build the output path with a _cleaned suffix.

    Examples:
        sales.xlsx  →  sales_cleaned.xlsx
        data.csv    →  data_cleaned.csv
        old.xls     →  old_cleaned.xlsx   (saved in the modern Excel format)
    """
    suffix = source.suffix.lower()
    if suffix == ".xls":
        suffix = ".xlsx"
    return output_dir / f"{source.stem}_cleaned{suffix}"


def column_name_looks_like_date(column_name: object) -> bool:
    """True if the column title contains a common date-related word."""
    name = str(column_name).lower()
    return any(hint in name for hint in DATE_NAME_HINTS)


def value_could_be_date(text: object) -> bool:
    """
    Quick check before we try to read a value as a date.

    It must show a year (2024, or a short date like 15/01/24) and must not be
    a plain number. This stops "2024" in a Year column, "00123" IDs,
    "09:30" times, and "Monday" from being changed.
    """
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text or PLAIN_NUMBER_PATTERN.match(text):
        return False
    return bool(FULL_YEAR_PATTERN.search(text) or SHORT_DATE_PATTERN.match(text))


def try_parse_dates(series: pd.Series) -> pd.Series:
    """
    Attempt to turn a column into real dates. Anything that isn't clearly a
    date becomes "NaT" (pandas' word for "not a time").

    Uses format='mixed' so values like 01/15/2024, 2024-01-15, and
    Jan 15 2024 can live in the same column. Ambiguous numbers like
    01/02/2023 are read as month/day/year (US style).
    """
    # Already real dates (common in Excel)? Keep as-is.
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    as_text = series.astype("string").str.strip()
    looks_like_date = as_text.map(value_could_be_date).astype(bool)
    candidates = as_text.where(looks_like_date)

    try:
        # format="mixed" needs pandas 2.0+
        return pd.to_datetime(candidates, errors="coerce", format="mixed")
    except (ValueError, TypeError, OverflowError):
        # Something unusual (like mixed time zones) — treat as "not dates"
        return pd.Series(pd.NaT, index=series.index)


def count_filled_cells(series: pd.Series) -> int:
    """How many cells in the column actually contain something."""
    as_text = series.astype("string").str.strip()
    return int((as_text.notna() & (as_text != "")).sum())


def should_treat_as_date_column(series: pd.Series, column_name: object) -> bool:
    """
    Decide whether this column should be normalized to YYYY-MM-DD.

    Rules (simple and cautious so we do not wreck other data):
      - Already real dates                                   → yes
      - Real numbers (not text)                              → no
      - Column name hints at a date AND at least half parse  → yes
      - No name hint, but nearly every value parses as a date → yes
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    # Number columns (amounts, IDs, years) are never treated as dates
    if pd.api.types.is_numeric_dtype(series):
        return False

    filled = count_filled_cells(series)
    if filled == 0:
        return False

    parsed = try_parse_dates(series)
    success_rate = parsed.notna().sum() / filled

    if column_name_looks_like_date(column_name) and success_rate >= 0.5:
        return True

    return success_rate >= DATE_PARSE_SUCCESS_RATE


def format_dates(parsed: pd.Series) -> pd.Series:
    """
    Turn real dates into text like 2024-01-15.

    If any value in the column has a time of day (not midnight), we keep it
    as 2024-01-15 14:30 so no information is lost.
    """
    has_time = (parsed.dropna() != parsed.dropna().dt.normalize()).any()
    pattern = "%Y-%m-%d %H:%M" if has_time else "%Y-%m-%d"
    return parsed.dt.strftime(pattern)


def normalize_dates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Convert date-like columns to text in YYYY-MM-DD form.

    Returns the updated table and a list of column names we changed
    (so we can print a friendly summary).
    """
    cleaned = df.copy()
    changed_columns: list[str] = []

    for column in cleaned.columns:
        series = cleaned[column]

        if not should_treat_as_date_column(series, column):
            continue

        parsed = try_parse_dates(series)
        formatted = format_dates(parsed)

        # Where a value wasn't a date (like "TBD"), keep the original text
        cleaned[column] = formatted.where(parsed.notna(), series).astype(object)

        changed_columns.append(str(column))

    return cleaned, changed_columns


def remove_duplicate_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Drop rows that are 100% identical to an earlier row.

    Returns (new_table, how_many_rows_were_removed).
    """
    before = len(df)
    # keep="first" means the first copy stays; later copies are removed
    deduped = df.drop_duplicates(keep="first")
    removed = before - len(deduped)
    return deduped, removed


def clean_table(df: pd.DataFrame, indent: str = "   ") -> pd.DataFrame:
    """Remove duplicates and fix dates in one table, printing what happened."""
    print(f"{indent}Loaded {len(df)} row(s) and {len(df.columns)} column(s).")

    # 1) Remove completely duplicate rows
    print(f"{indent}Removing completely duplicate rows...")
    df, removed = remove_duplicate_rows(df)
    if removed:
        print(f"{indent}Removed {removed} duplicate row(s). {len(df)} row(s) remain.")
    else:
        print(f"{indent}No completely duplicate rows found. Nice!")

    # 2) Standardize date columns to YYYY-MM-DD
    print(f"{indent}Checking for inconsistent date formats...")
    df, date_cols = normalize_dates(df)
    if date_cols:
        print(f"{indent}Standardized dates in: {', '.join(date_cols)}")
    else:
        print(f"{indent}No date-like columns needed changing.")

    return df


def save_spreadsheet(sheets: dict[str, pd.DataFrame], destination: Path) -> None:
    """Write the cleaned table(s) back out as CSV or Excel."""
    if destination.suffix == ".csv":
        table = next(iter(sheets.values()))
        # index=False = do not add an extra "0,1,2..." column on the left.
        # utf-8-sig lets Excel open the file with symbols like £ and é intact.
        table.to_csv(destination, index=False, encoding="utf-8-sig")
        return

    try:
        # One workbook, same sheet names and order as the original
        with pd.ExcelWriter(destination, engine="openpyxl") as writer:
            for sheet_name, table in sheets.items():
                table.to_excel(writer, sheet_name=sheet_name, index=False)
    except ImportError as err:
        raise RuntimeError(
            "Saving Excel files needs the 'openpyxl' library. Run:  pip install openpyxl"
        ) from err


def process_one_file(source: Path, output_dir: Path, index: int, total: int) -> None:
    """Read → clean → save one spreadsheet, with friendly progress messages."""
    print(f"Cleaning file {index} of {total}: {source.name} ...")

    try:
        sheets = read_spreadsheet(source)
    except Exception as err:
        print(f"   ⚠️  Could not open this file — skipped. Reason: {err}")
        print()
        return

    try:
        if len(sheets) == 1:
            cleaned = {name: clean_table(df) for name, df in sheets.items()}
        else:
            print(f"   This workbook has {len(sheets)} sheets — cleaning each one.")
            cleaned = {}
            for name, df in sheets.items():
                print(f"   Sheet '{name}':")
                cleaned[name] = clean_table(df, indent="      ")
    except Exception as err:
        print(f"   ⚠️  Something went wrong while cleaning — skipped. Reason: {err}")
        print()
        return

    destination = cleaned_output_path(source, output_dir)
    if source.suffix.lower() == ".xls":
        print("   Note: older .xls files are saved as modern .xlsx after cleaning.")

    try:
        save_spreadsheet(cleaned, destination)
    except Exception as err:
        print(f"   ⚠️  Could not save the cleaned file — skipped. Reason: {err}")
        print()
        return

    print(f"   Done! Saved as: {destination.name}")
    print()


# ---------------------------------------------------------------------------
# Main program — runs when you type: python excel_cleaner.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Spreadsheet Cleaner")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    files = find_spreadsheets(input_dir)

    if not files:
        print("No Excel or CSV files found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your .xlsx / .xls / .csv files into it.")
        print("  3. Run this script again:")
        print()
        print("         python excel_cleaner.py")
        print()
        return

    total = len(files)
    print(f"Found {total} spreadsheet(s) to clean. Starting now...")
    print()

    for i, path in enumerate(files, start=1):
        process_one_file(path, output_dir, i, total)

    print("=" * 60)
    print("All done! Check the 'cleaned_spreadsheets' folder for your files.")
    print("Originals in 'input_spreadsheets' were left untouched.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

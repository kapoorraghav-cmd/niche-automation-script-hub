#!/usr/bin/env python3
"""
Spreadsheet Cleaner
===================
This script looks in an "input_spreadsheets" folder for Excel (.xlsx / .xls)
or CSV (.csv) files, then for each file it:

  1. Removes completely duplicate rows (every column the same)
  2. Fixes inconsistent date values to a standard YYYY-MM-DD format
  3. Saves a new file with a "_cleaned" suffix into "cleaned_spreadsheets"

Your original files are never changed.

How to run (after following README.md):
    python excel_cleaner.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus pandas / openpyxl for spreadsheet work
# ---------------------------------------------------------------------------

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
    print("    pip install pandas openpyxl")
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

# If at least this fraction of non-empty values in a column look like dates,
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
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            # Skip macOS junk files and already-cleaned copies if someone
            # accidentally drops them in the input folder
            if item.name.startswith(".$") or item.name.startswith("~$"):
                continue
            files.append(item)

    return sorted(files, key=lambda p: p.name.lower())


def read_spreadsheet(path: Path) -> pd.DataFrame:
    """
    Load one spreadsheet into a pandas DataFrame (a table in memory).

    - CSV  → read_csv
    - XLSX → read_excel (needs openpyxl)
    - XLS  → read_excel (older Excel format; may need xlrd on some systems)
    """
    suffix = path.suffix.lower()

    if suffix == ".csv":
        # encoding="utf-8-sig" handles Excel-exported CSVs that start with a BOM
        return pd.read_csv(path, encoding="utf-8-sig")

    if suffix in {".xlsx", ".xls"}:
        # engine is chosen automatically when possible; openpyxl handles .xlsx
        try:
            return pd.read_excel(path)
        except ImportError as err:
            # Most common missing piece for .xlsx is openpyxl
            print("   ⚠️  Excel support needs an extra library.")
            print("   Run:  pip install openpyxl")
            raise SystemExit(1) from err

    raise ValueError(f"Unsupported file type: {suffix}")


def cleaned_output_path(source: Path, output_dir: Path) -> Path:
    """
    Build the output path with a _cleaned suffix.

    Examples:
        sales.xlsx  →  sales_cleaned.xlsx
        data.csv    →  data_cleaned.csv
    """
    return output_dir / f"{source.stem}_cleaned{source.suffix.lower()}"


def column_name_looks_like_date(column_name: object) -> bool:
    """True if the column title contains a common date-related word."""
    name = str(column_name).lower()
    return any(hint in name for hint in DATE_NAME_HINTS)


def try_parse_dates(series: pd.Series) -> pd.Series:
    """
    Attempt to turn a column into real dates.

    Uses format='mixed' so values like 01/15/2024, 2024-01-15, and
    Jan 15 2024 can live in the same column. Ambiguous numbers like
    01/02/2023 are read as month/day/year (US style).
    """
    # Already a datetime column? Keep as-is (we'll format later).
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    # Turn everything into text first so "01/02/2024" and Excel leftovers mix safely
    as_text = series.astype("string")

    # format="mixed" needs pandas 2.0+
    return pd.to_datetime(as_text, errors="coerce", format="mixed")


def should_treat_as_date_column(series: pd.Series, column_name: object) -> bool:
    """
    Decide whether this column should be normalized to YYYY-MM-DD.

    Rules (simple and cautious so we do not wreck ID numbers):
      - Already datetime  → yes
      - Column name hints at a date AND at least half the values parse → yes
      - No name hint, but a very high % of values parse as dates → yes
      - Mostly plain numbers with no date-like name → no (avoids turning IDs into dates)
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    non_null = series.dropna()
    if non_null.empty:
        return False

    name_hint = column_name_looks_like_date(column_name)

    # Pure numeric columns without a date-ish name are almost never "dates"
    # people typed by hand — skip them to protect invoice numbers, years-as-IDs, etc.
    if pd.api.types.is_numeric_dtype(series) and not name_hint:
        return False

    parsed = try_parse_dates(series)
    success_rate = parsed.notna().sum() / max(len(non_null), 1)

    if name_hint and success_rate >= 0.5:
        return True

    if success_rate >= DATE_PARSE_SUCCESS_RATE:
        return True

    return False


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

        # Keep blank cells blank; format real dates as 2024-01-15
        formatted = parsed.dt.strftime("%Y-%m-%d")
        # Where parsing failed, leave the original value alone
        # (so a rare bad cell does not become empty forever)
        original_as_string = series.astype("string")
        cleaned[column] = formatted.fillna(original_as_string)

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


def save_spreadsheet(df: pd.DataFrame, destination: Path, source_suffix: str) -> None:
    """Write the cleaned table back out as CSV or Excel, matching the input type."""
    suffix = source_suffix.lower()

    if suffix == ".csv":
        # index=False = do not add an extra "0,1,2..." column on the left
        df.to_csv(destination, index=False, encoding="utf-8-sig")
        return

    if suffix in {".xlsx", ".xls"}:
        # Always save cleaned Excel as .xlsx (modern format). If the source
        # was old .xls, we still write .xlsx but keep the chosen destination
        # name unless it still says .xls — normalize that here.
        if destination.suffix.lower() == ".xls":
            destination = destination.with_suffix(".xlsx")
        try:
            df.to_excel(destination, index=False, engine="openpyxl")
        except ImportError as err:
            print("   ⚠️  Saving Excel files needs openpyxl.")
            print("   Run:  pip install openpyxl")
            raise SystemExit(1) from err
        return

    raise ValueError(f"Unsupported output type: {suffix}")


def process_one_file(source: Path, output_dir: Path, index: int, total: int) -> None:
    """Read → clean → save one spreadsheet, with friendly progress messages."""
    print(f"Cleaning file {index} of {total}: {source.name} ...")

    try:
        df = read_spreadsheet(source)
    except Exception as err:
        print(f"   ⚠️  Could not open this file — skipped. Reason: {err}")
        print()
        return

    rows_before = len(df)
    cols_before = len(df.columns)
    print(f"   Loaded {rows_before} row(s) and {cols_before} column(s).")

    # 1) Remove completely duplicate rows
    print("   Removing completely duplicate rows...")
    df, removed = remove_duplicate_rows(df)
    if removed:
        print(f"   Removed {removed} duplicate row(s). {len(df)} row(s) remain.")
    else:
        print("   No completely duplicate rows found. Nice!")

    # 2) Standardize date columns to YYYY-MM-DD
    print("   Checking for inconsistent date formats...")
    df, date_cols = normalize_dates(df)
    if date_cols:
        print(f"   Standardized dates in: {', '.join(date_cols)}")
    else:
        print("   No date-like columns needed changing.")

    # 3) Save with _cleaned suffix
    destination = cleaned_output_path(source, output_dir)
    # Old .xls inputs become .xlsx outputs (more reliable)
    if source.suffix.lower() == ".xls":
        destination = destination.with_suffix(".xlsx")
        print("   Note: older .xls files are saved as modern .xlsx after cleaning.")

    try:
        save_spreadsheet(df, destination, source.suffix)
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

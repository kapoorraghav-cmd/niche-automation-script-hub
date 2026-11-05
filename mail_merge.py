#!/usr/bin/env python3
"""
Mail-Merge Certificates & Letters
=================================
This script turns ONE Word template plus ONE spreadsheet of people into one
personalised Word document per person — certificates, offer letters,
invitations, award letters, name badges ...

  1. In the "mail_merge" folder, put a Word template (.docx) and a
     spreadsheet (.xlsx, .xls or .csv) with one row per person.
  2. In the template, type the spreadsheet's column headings inside double
     curly braces wherever a person's details should go, for example:

         This certifies that {{First Name}} {{Last Name}} completed {{Course}}.

  3. Run the script. It checks every placeholder has a matching column,
     asks before making anything, then saves one document per row into the
     "merged_documents" folder (plus PDF copies if LibreOffice is installed).

The first time you run it, an example certificate and spreadsheet are added
to the "mail_merge" folder so you can see how it works straight away.

Your template and spreadsheet are never changed.

How to run (after following README.md):
    python mail_merge.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus docxtpl / pandas for Word and spreadsheet work
# ---------------------------------------------------------------------------

import csv  # Writes the example spreadsheet
import datetime  # Recognises real dates and times from Excel
import difflib  # Finds the closest column name when a placeholder has a typo
import html  # Turns "&amp;" inside Word's files back into "&"
import io  # Lets us keep the template in memory instead of re-opening the file
import math  # Spots "not a number" values (empty Excel cells)
import os  # Reads the "Program Files" location on Windows
import re  # "Regular expressions" — a way to spot text patterns like {{Name}}
import shutil  # Finds programs (LibreOffice) installed on this computer
import subprocess  # Runs LibreOffice to make the PDF copies
import sys  # Gives access to the terminal output settings
import tempfile  # A throw-away folder for LibreOffice's settings
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional

# docxtpl = fills in Word templates (it brings python-docx, which reads and
#           writes .docx files, and jinja2, which does the filling in)
# pandas  = reads the spreadsheet; openpyxl / xlrd let it open Excel files
try:
    import pandas as pd
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    from docxtpl import DocxTemplate
except ImportError:
    print()
    print("=" * 60)
    print("Oops! A library this tool needs is not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install -r requirements.txt")
    print()
    print("Or install just the mail-merge tools:")
    print()
    print("    pip install docxtpl pandas openpyxl xlrd")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the Word template and the spreadsheet of people
INPUT_FOLDER_NAME = "mail_merge"

# Folder where THIS SCRIPT saves the finished documents
OUTPUT_FOLDER_NAME = "merged_documents"

# How each finished document is named. Use the same {{Column Name}}
# placeholders as in the template. A row with nothing to put in the name
# (for example blank name cells) is called Document_001, Document_002 ...
FILE_NAME_PATTERN = "{{First Name}} {{Last Name}}"

# How real dates from Excel are written into the documents.
#   "%d %B %Y"  →  05 March 2026      "%B %d, %Y"  →  March 05, 2026
#   "%d/%m/%Y"  →  05/03/2026         "%Y-%m-%d"   →  2026-03-05
# (%d = day, %m = month number, %B = month name, %Y = 4-digit year.)
# Dates in a CSV file are plain text, so they are always used exactly as typed.
DATE_FORMAT = "%d %B %Y"

# How times of day from Excel are written (%H = hour 00-23, %M = minutes)
TIME_FORMAT = "%H:%M"

# Also save a PDF copy of every document? This needs LibreOffice, a free
# office program (https://www.libreoffice.org/download/). Without it you
# still get all the Word documents.
MAKE_PDFS = True

# When PDFs are made, also join them into one big PDF — handy for printing
# every certificate in one go. (Needs the pypdf library: pip install pypdf)
COMBINE_INTO_ONE_PDF = False
COMBINED_PDF_NAME = "All documents.pdf"

# The example files written into an empty "mail_merge" folder
EXAMPLE_TEMPLATE_NAME = "example_template.docx"
EXAMPLE_DATA_NAME = "example_people.csv"

# File endings we accept (case-insensitive)
TEMPLATE_EXTENSIONS = {".docx"}
DATA_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Word formats that can't be used as a template — we explain how to fix them
OLD_WORD_EXTENSIONS = {".doc", ".dotx", ".docm", ".dot", ".odt", ".rtf"}

# Text encodings to try when opening a CSV, in order.
# Excel on Windows often saves CSVs as "cp1252" rather than "utf-8",
# which is why a "£" sign can stop a CSV from opening.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

# Windows does not allow these characters in file names. We replace them on
# every computer so the documents can still be copied to a Windows PC.
INVALID_CHARACTERS = '\\/:*?"<>|'

# Names Windows reserves for itself — a file can't be called "CON.docx"
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{kind}{n}" for kind in ("COM", "LPT") for n in range(1, 10)
}

# Very long names can break on Windows, which limits the length of a full path
MAX_FILE_NAME_LENGTH = 100

# How many example file names to show before asking
PREVIEW_NAMES = 3

# LibreOffice converts documents in groups of this many (very long commands
# can fail on Windows), and gets this many seconds per document.
PDF_BATCH_SIZE = 50
PDF_SECONDS_PER_DOCUMENT = 30


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class Placeholder(NamedTuple):
    """One {{...}} found in the template: as typed, its matching key, and where."""

    text: str
    key: str
    location: str


class Row(NamedTuple):
    """One person from the spreadsheet: its row number there and its cell values."""

    number: int
    values: list


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
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_files(folder: Path, extensions: set) -> list[Path]:
    """Return the files in the folder (not subfolders) with one of these endings."""
    files = []
    for item in folder.iterdir():
        # Skip hidden files and the temporary "~$letter.docx" lock files
        # Word and Excel create while a file is open — they are not real files.
        if item.name.startswith((".", "~$")):
            continue
        if item.is_file() and item.suffix.lower() in extensions:
            files.append(item)

    return sorted(files, key=lambda p: p.name.lower())


def match_key(text: str) -> str:
    """
    Turn a placeholder or column heading into a simple "matching key", so
    {{First Name}}, {{ first   name }} and {{FIRST NAME}} all match the
    column "First Name".

    It also undoes Word's "smart quotes" (’ → ') so {{Manager’s Name}}
    still matches a column typed as Manager's Name.
    """
    text = html.unescape(text)
    for curly, straight in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(curly, straight)
    # split() + join collapses every run of spaces (including Word's
    # "non-breaking" spaces and line breaks) into one normal space
    return " ".join(text.split()).casefold()


def tidy_placeholder(text: str) -> str:
    """How a placeholder is shown in messages: {{First Name}}."""
    return "{{" + " ".join(html.unescape(text).split()) + "}}"


# --- Reading the Word template ----------------------------------------------
#
# Inside a .docx file, every piece of text lives in XML "runs" like
#     <w:r><w:t>Hello</w:t></w:r>
# Word often splits what you typed into several runs (after a spell-check,
# a formatting change, or an edit), so {{First Name}} might really be stored
# as "{{", "First Na", "me}}". These patterns find placeholders even then.

# A "{" or "}" followed by XML tags and then another "{" or "}" — a pair of
# braces that Word split in two
SPLIT_BRACES = re.compile(r"(?<=\{)(?:<[^>]*>)+(?=\{)|(?<=\})(?:<[^>]*>)+(?=\})")

# {{ ... }} — the part in between may contain XML tags (from split runs),
# but must stay inside one paragraph (</w:p> ends a paragraph)
PLACEHOLDER_IN_XML = re.compile(r"\{\{((?:(?!\{\{|\}\}|</w:p>).)*?)\}\}", re.DOTALL)

# One XML tag: <w:r>, </w:t>, <w:br/> ...
XML_TAG = re.compile(r"<(/?)([\w:.-]+)[^>]*?(/?)>")

# Brace pairs that would confuse the template engine if left in the text.
# docxtpl turns "{_{" back into "{{" (and so on) when it is finished.
LEFTOVER_BRACES = (("{{", "{_{"), ("}}", "}_}"), ("{%", "{_%"), ("%}", "%_}"), ("{#", "{_#"))

# A placeholder in FILE_NAME_PATTERN
PLACEHOLDER_IN_TEXT = re.compile(r"\{\{(.*?)\}\}")


def tags_are_balanced(xml_between: str) -> bool:
    """
    Check the XML inside a split placeholder only closes some runs and opens
    new ones (like "</w:t></w:r><w:r><w:t>"), so removing it is safe.

    It isn't safe when a placeholder is half inside something else, for
    example half of it is a web link or a tracked change.
    """
    still_open: list[str] = []
    closed_early: list[str] = []
    for closing, name, self_closing in XML_TAG.findall(xml_between):
        if self_closing:
            continue
        if not closing:
            still_open.append(name)
        elif still_open and still_open[-1] == name:
            still_open.pop()
        else:
            closed_early.append(name)
    return closed_early == still_open[::-1]


def nearby_text(xml: str, position: int, length: int = 40) -> str:
    """The readable text just after a position in the XML, for error messages."""
    paragraph_rest = xml[position:position + 3000].split("</w:p>")[0]
    text = html.unescape(re.sub(r"<[^>]+>", "", paragraph_rest))
    return " ".join(text.split())[:length]


class MergeTemplate(DocxTemplate):
    """
    docxtpl's Word template, taught to understand friendly placeholders.

    docxtpl expects computer-style names like {{ first_name }}. People type
    {{First Name}} (with spaces and capitals), so before docxtpl reads the
    template we swap each friendly placeholder for a safe name like
    {{ col_0 }} — "the value from column 0". Everything else in the template
    (fonts, colours, tables, pictures, headers and footers) is untouched.
    """

    def __init__(self, template_bytes: bytes, variable_names: Optional[dict] = None):
        # The template is read from memory, so the original file is never
        # opened for writing.
        super().__init__(io.BytesIO(template_bytes))
        self.variable_names = variable_names or {}  # matching key → col_N
        self.found: list[Placeholder] = []
        self.problems: list[str] = []
        self.location = "main text"

    def patch_xml(self, src_xml: str) -> str:
        # docxtpl calls this for the main text, headers, footers and
        # footnotes. Text boxes are part of the main text.
        return super().patch_xml(self.make_placeholders_safe(src_xml))

    def render_xml_part(self, src_xml, part, context, jinja_env=None):
        xml = super().render_xml_part(src_xml, part, context, jinja_env)
        # Put back any "{#" we protected in make_placeholders_safe
        return xml.replace("{_#", "{#")

    def render_properties(self, context, jinja_env=None) -> None:
        # docxtpl would also fill in the document's hidden properties (title,
        # author ...). We leave them exactly as they are in your template.
        return

    def make_placeholders_safe(self, xml: str) -> str:
        """Swap every friendly {{Column Name}} in this XML for {{ col_N }}."""
        xml = SPLIT_BRACES.sub("", xml)
        replacements: list[str] = []

        def swap(match: re.Match) -> str:
            inside = match.group(1)
            if not tags_are_balanced(inside):
                self.problems.append(
                    f"{tidy_placeholder(re.sub(r'<[^>]+>', '', inside))} (in the {self.location}) "
                    "is partly inside a link, a tracked change or another special area. "
                    "Delete it and type it again in one go."
                )
                return match.group(0)

            text = re.sub(r"<[^>]+>", "", inside)
            key = match_key(text)
            if not key:
                self.problems.append(
                    f"There is an empty {{{{}}}} in the {self.location}. "
                    "Type a column heading between the braces, or delete them."
                )
                return match.group(0)

            self.found.append(Placeholder(tidy_placeholder(text), key, self.location))
            # The XML tags in between are dropped, so the whole placeholder
            # takes the formatting (font, size, colour) of its first part.
            replacements.append("{{ " + self.variable_names.get(key, "missing_column") + " }}")
            # \x00 can never appear in a Word file, so it is a safe marker
            return f"\x00{len(replacements) - 1}\x00"

        xml = PLACEHOLDER_IN_XML.sub(swap, xml)

        # Any "{{" or "}}" still left is a placeholder with a brace missing
        for broken in re.finditer(r"\{\{|\}\}", xml):
            self.problems.append(
                f"A placeholder in the {self.location} is missing a brace near: "
                f"\"{nearby_text(xml, max(0, broken.start() - 20), 60)}\". "
                "Each one needs two at the start and two at the end, like {{First Name}}."
            )
        # Protect stray braces (and things like "{%" or "{#" in normal text)
        # so they appear in the documents exactly as typed.
        for raw, protected in LEFTOVER_BRACES:
            xml = xml.replace(raw, protected)

        return re.sub(r"\x00(\d+)\x00", lambda m: replacements[int(m.group(1))], xml)

    def scan(self) -> None:
        """Read every part of the template once, collecting placeholders and problems."""
        self.init_docx()
        self.location = "main text"
        self.patch_xml(self.get_xml())
        for uri, name in ((self.HEADER_URI, "header"), (self.FOOTER_URI, "footer")):
            for _, part in self.get_headers_footers(uri):
                self.location = name
                self.patch_xml(self.get_part_xml(part))
        self.location = "footnotes"
        for part in self.docx.part.package.parts:
            if part.content_type.endswith("footnotes+xml"):
                self.patch_xml(part.blob.decode("utf-8"))


# --- Reading the spreadsheet --------------------------------------------------

def read_csv_any_encoding(path: Path) -> pd.DataFrame:
    """
    Read a CSV file, trying a few common text encodings until one works.

    dtype=str reads every cell as text, so nothing gets changed by accident
    (for example, ID 00123 keeps its leading zeros).

    keep_default_na=False + na_values=[""] means only truly empty cells count
    as blank. Without this, pandas would quietly wipe out text like "N/A".

    skip_blank_lines=False keeps empty lines, so the row numbers in our
    messages match the row numbers you see in Excel.
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
                skip_blank_lines=False,
            )
        except UnicodeDecodeError as err:
            last_error = err  # Wrong encoding — try the next one
    raise last_error


def read_spreadsheet(path: Path) -> tuple[pd.DataFrame, str]:
    """
    Load the spreadsheet as a table. Returns (table, note), where the note
    says which sheet was used when an Excel file has several.
    """
    if path.suffix.lower() == ".csv":
        return read_csv_any_encoding(path), ""

    try:
        with pd.ExcelFile(path) as book:
            sheet = book.sheet_names[0]
            # dtype=object keeps each cell as Excel stored it: text stays
            # text (00123 keeps its zeros) and real dates stay dates.
            table = book.parse(sheet, dtype=object, keep_default_na=False, na_values=[""])
    except ImportError as err:
        library = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
        raise RuntimeError(
            f"Reading {path.suffix} files needs the '{library}' library. "
            f"Run:  pip install {library}"
        ) from err

    note = ""
    if len(book.sheet_names) > 1:
        note = f"Using the first sheet, '{sheet}' (this workbook has {len(book.sheet_names)} sheets)."
    return table, note


def cell_to_text(value: object) -> str:
    """
    Turn one spreadsheet cell into the text that goes into the document.

      - Text is kept exactly as typed (00123 stays 00123, N/A stays N/A)
      - Real Excel dates use DATE_FORMAT (05 March 2026)
      - Whole numbers lose the ".0" Excel sometimes adds (5.0 → 5)
      - Empty cells become empty text
    """
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            if pd.isna(value):  # Empty cell, "not a number" or "not a time"
                return ""
        except (TypeError, ValueError):
            pass

        if pd.api.types.is_bool(value):
            text = "TRUE" if value else "FALSE"  # As Excel shows them
        elif isinstance(value, datetime.datetime):
            text = value.strftime(DATE_FORMAT)
            if value.time() != datetime.time(0, 0):
                text += " " + value.strftime(TIME_FORMAT)
        elif isinstance(value, datetime.date):
            text = value.strftime(DATE_FORMAT)
        elif isinstance(value, datetime.time):
            text = value.strftime(TIME_FORMAT)
        elif pd.api.types.is_integer(value):
            text = str(int(value))
        elif pd.api.types.is_float(value):
            if math.isinf(value):
                text = str(value)
            elif float(value).is_integer():
                text = str(int(value))
            else:
                # Up to 10 decimal places, without the extra zeros at the end
                # (and without tiny rounding leftovers like 0.30000000000000004)
                text = f"{value:.10f}".rstrip("0").rstrip(".")
        else:
            text = str(value)

    # Line breaks typed in a cell (Alt+Enter in Excel) become line breaks in
    # Word. Other invisible control characters aren't allowed in Word files.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def column_title(raw: object) -> str:
    """A column heading as text. Headings left empty come back as ""."""
    title = " ".join(str(raw).split())
    # pandas calls a column with no heading "Unnamed: 3"
    return "" if re.fullmatch(r"Unnamed: \d+(\.\d+)?", title) else title


def table_to_rows(table: pd.DataFrame) -> tuple[list[Row], int]:
    """
    Turn the table into a list of rows of text, skipping completely empty
    rows. Returns (rows, how_many_empty_rows_were_skipped).
    """
    rows: list[Row] = []
    empty = 0
    for position, values in enumerate(table.itertuples(index=False, name=None)):
        texts = [cell_to_text(v) for v in values]
        if not any(t.strip() for t in texts):
            empty += 1
            continue
        # Row 1 holds the headings, so the first person is on row 2
        rows.append(Row(position + 2, texts))
    return rows, empty


# --- Checking, naming and making the documents --------------------------------

def find_closest_column(key: str, column_keys: dict) -> Optional[str]:
    """The column heading that looks most like a misspelled placeholder."""
    close = difflib.get_close_matches(key, list(column_keys), n=1, cutoff=0.6)
    return column_keys[close[0]][1] if close else None


def make_safe_file_name(text: str) -> str:
    """
    Turn text like 'A/B: Smith?' into a file name every computer accepts.

    Characters Windows can't use become "_", extra spaces are tidied, and
    dots or spaces at the very start or end are removed. Returns "" if
    nothing usable is left.
    """
    text = " ".join(text.split())
    text = "".join("_" if c in INVALID_CHARACTERS or ord(c) < 32 else c for c in text)
    text = text.strip(" .")[:MAX_FILE_NAME_LENGTH].rstrip(" .")
    if text.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        text += "_"
    return text


def plan_file_names(rows: list[Row], column_keys: dict) -> list[str]:
    """
    Work out a file name (without .docx) for every row, using
    FILE_NAME_PATTERN. Repeated names get _2, _3 ... so nothing is lost.
    """
    pattern_keys = [match_key(t) for t in PLACEHOLDER_IN_TEXT.findall(FILE_NAME_PATTERN)]
    pattern_works = all(key in column_keys for key in pattern_keys)
    digits = max(3, len(str(len(rows))))

    names: list[str] = []
    used: set = set()
    for number, row in enumerate(rows, start=1):
        name = ""
        if pattern_works:
            filled = PLACEHOLDER_IN_TEXT.sub(
                lambda m: row.values[column_keys[match_key(m.group(1))][0]], FILE_NAME_PATTERN
            )
            name = make_safe_file_name(filled)
        if not name:
            name = f"Document_{number:0{digits}d}"

        # Mac and Windows treat "Ada.docx" and "ada.docx" as the SAME file,
        # so we compare names ignoring capital letters.
        unique, copy = name, 2
        while unique.casefold() in used:
            unique = f"{name}_{copy}"
            copy += 1
        used.add(unique.casefold())
        names.append(unique)
    return names


def show_check(
    template_path: Path,
    data_path: Path,
    found: list[Placeholder],
    columns: list[str],
    column_keys: dict,
    rows: list[Row],
) -> bool:
    """
    Print what will happen and check every placeholder has a column.
    Returns False (after explaining) if something must be fixed first.
    """
    print(f"Template:     {template_path.name}")
    print(f"Spreadsheet:  {data_path.name}  ({len(rows)} row(s) of data)")
    print()

    # One line per different placeholder, in the order they appear
    seen: dict[str, Placeholder] = {}
    places: dict[str, list[str]] = {}
    for p in found:
        seen.setdefault(p.key, p)
        if p.location not in places.setdefault(p.key, []):
            places[p.key].append(p.location)

    missing = [p for key, p in seen.items() if key not in column_keys]
    if missing:
        print("⚠️  Stopped: these placeholders don't match any column heading in the spreadsheet:")
        for p in missing:
            closest = find_closest_column(p.key, column_keys)
            hint = f"did you mean {{{{{closest}}}}}?" if closest else "no similar column found"
            print(f"   {p.text}  ({hint})")
        print()
        print(f"The column headings in {data_path.name} are:")
        print(f"   {', '.join(columns)}")
        print()
        print("To fix it, make the placeholder in the Word template and the column heading")
        print("in the spreadsheet use the same words (capital letters and extra spaces")
        print("don't matter), then run this script again. Nothing was created.")
        print()
        return False

    width = min(30, max(len(p.text) for p in seen.values()))
    print("Placeholders found in the template:")
    for key, p in seen.items():
        where = [place for place in places[key] if place != "main text"]
        extra = ""
        if where:
            also = "also " if "main text" in places[key] else ""
            extra = f"  ({also}in the {' and '.join(where)})"
        print(f"   {p.text:<{width}}  →  column \"{column_keys[key][1]}\"{extra}")

    unused = [title for key, (_, title) in column_keys.items() if key not in seen]
    if unused:
        print(f"Columns not used in the template (that's fine): {', '.join(unused)}")
    print()
    return True


def make_document(template_bytes: bytes, variable_names: dict, row: Row, destination: Path) -> None:
    """Fill in the template for one person and save it."""
    document = MergeTemplate(template_bytes, variable_names)
    context = {f"col_{i}": value for i, value in enumerate(row.values)}
    # autoescape=True keeps characters like & and < in names (Smith & Co)
    # from breaking the Word file.
    document.render(context, autoescape=True)
    document.save(destination)


# --- PDF copies with LibreOffice ---------------------------------------------

def find_libreoffice() -> Optional[str]:
    """Return the path of LibreOffice's 'soffice' program, or None if not installed."""
    candidates: list[Optional[str]] = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                     r"C:\Program Files", r"C:\Program Files (x86)"):
            if base:
                # soffice.com waits until the conversion is finished; .exe may not
                candidates.append(str(Path(base) / "LibreOffice" / "program" / "soffice.com"))
                candidates.append(str(Path(base) / "LibreOffice" / "program" / "soffice.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        candidates.append(str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"))
    else:
        candidates += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                       "/opt/libreoffice/program/soffice", "/snap/bin/libreoffice"]
    candidates += [shutil.which("soffice"), shutil.which("libreoffice")]

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def last_message(result: subprocess.CompletedProcess) -> str:
    """The last line LibreOffice printed — usually the reason something failed."""
    lines = [line.strip() for line in f"{result.stdout}\n{result.stderr}".splitlines() if line.strip()]
    return lines[-1][:200] if lines else f"it stopped with error code {result.returncode}"


def convert_to_pdfs(soffice: str, documents: list[Path], output_dir: Path) -> tuple[list[Path], str]:
    """
    Ask LibreOffice to turn the Word documents into PDFs, in batches.
    Returns (the PDFs that were made, the reason if some were not).
    """
    made: list[Path] = []
    reason = ""
    # A separate, temporary LibreOffice settings folder means this works
    # even while you have LibreOffice open for something else.
    with tempfile.TemporaryDirectory(prefix="mail_merge_lo_") as profile:
        for start in range(0, len(documents), PDF_BATCH_SIZE):
            batch = documents[start:start + PDF_BATCH_SIZE]
            for doc in batch:
                try:
                    doc.with_suffix(".pdf").unlink()  # An old copy from an earlier run
                except FileNotFoundError:
                    pass
                except OSError:
                    pass  # Open in a PDF viewer? LibreOffice will report it.

            command = [
                soffice,
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                *[str(doc) for doc in batch],
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=60 + PDF_SECONDS_PER_DOCUMENT * len(batch),
                )
                if result.returncode != 0:
                    reason = last_message(result)
            except subprocess.TimeoutExpired:
                reason = "LibreOffice took too long and was stopped"
            except OSError as err:
                reason = str(err)

            made += [doc.with_suffix(".pdf") for doc in batch if doc.with_suffix(".pdf").exists()]
            if len(documents) > PDF_BATCH_SIZE:
                print(f"   Converted {start + len(batch)} of {len(documents)} documents...")
    return made, reason


def combine_pdfs(pdfs: list[Path], destination: Path) -> None:
    """Join several PDFs into one, in the same order."""
    from pypdf import PdfWriter  # Only needed for this optional step

    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(str(pdf))
    with open(destination, "wb") as f:
        writer.write(f)


def explain_how_to_get_pdfs() -> None:
    print("📄 No PDF copies: LibreOffice (free) isn't installed on this computer.")
    print("   Your Word documents are all saved. To get PDFs too:")
    print("     1. Download LibreOffice from https://www.libreoffice.org/download/")
    print("     2. Install it, then run this script again.")
    print("   (Or set MAKE_PDFS = False at the top of this script to hide this message.)")
    print()


def make_pdfs(documents: list[Path], output_dir: Path) -> int:
    """Make PDF copies (and optionally one combined PDF). Returns how many were made."""
    soffice = find_libreoffice()
    if not soffice:
        explain_how_to_get_pdfs()
        return 0

    print("Making PDF copies with LibreOffice (this can take a minute)...")
    pdfs, reason = convert_to_pdfs(soffice, documents, output_dir)

    if not pdfs:
        print(f"   ⚠️  LibreOffice didn't create any PDFs. Reason: {reason or 'unknown'}")
        print("   Your Word documents are all saved. Check LibreOffice opens normally on its")
        print("   own, or reinstall it from https://www.libreoffice.org/download/")
        print()
        return 0

    if len(pdfs) < len(documents):
        failed = [doc.name for doc in documents if doc.with_suffix(".pdf") not in pdfs]
        print(f"   ⚠️  {len(failed)} document(s) could not be turned into PDFs: {', '.join(failed[:5])}"
              + (" ..." if len(failed) > 5 else ""))
        if reason:
            print(f"   Reason: {reason}")
    print(f"   Done! Made {len(pdfs)} PDF(s).")

    if COMBINE_INTO_ONE_PDF:
        destination = output_dir / COMBINED_PDF_NAME
        try:
            combine_pdfs(pdfs, destination)
            print(f"   Done! Joined them into one file: {destination.name}")
        except ImportError:
            print("   ⚠️  Joining the PDFs needs the pypdf library. Run:  pip install pypdf")
        except Exception as err:
            print(f"   ⚠️  Could not join the PDFs into one file. Reason: {err}")
    print()
    return len(pdfs)


# --- Example files ----------------------------------------------------------

def add_text(document, text: str, size: int, bold: bool = False, italic: bool = False,
             color: Optional[RGBColor] = None, space_after: int = 10, font: str = "Georgia") -> None:
    """Add one centred line of text to the example certificate."""
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(space_after)
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.name = font
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = color


def create_example_files(folder: Path) -> None:
    """Write a simple certificate template and a matching spreadsheet."""
    navy = RGBColor(0x1F, 0x4E, 0x79)
    grey = RGBColor(0x59, 0x59, 0x59)

    document = Document()
    section = document.sections[0]
    # A4, turned sideways (landscape) like most certificates
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(2.2))

    # A double-line border around the page. Word keeps page borders in the
    # page settings, right after the margins.
    borders = OxmlElement("w:pgBorders")
    borders.set(qn("w:offsetFrom"), "page")
    for side in ("top", "left", "bottom", "right"):
        line = OxmlElement(f"w:{side}")
        line.set(qn("w:val"), "double")
        line.set(qn("w:sz"), "18")
        line.set(qn("w:space"), "24")
        line.set(qn("w:color"), "1F4E79")
        borders.append(line)
    section._sectPr.find(qn("w:pgMar")).addnext(borders)

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_run = header.add_run("Certificate No. {{Certificate No}}")
    header_run.font.size = Pt(10)
    header_run.font.color.rgb = grey

    add_text(document, "", 12, space_after=18)
    add_text(document, "CERTIFICATE OF COMPLETION", 34, bold=True, color=navy, space_after=18)
    add_text(document, "This is to certify that", 14, italic=True, color=grey)
    add_text(document, "{{First Name}} {{Last Name}}", 32, bold=True, space_after=12)
    add_text(document, "has successfully completed the course", 14, italic=True, color=grey)
    add_text(document, "{{Course}}", 22, bold=True, color=navy, space_after=36)

    # A two-column table for the signature and date lines
    table = document.add_table(rows=2, cols=2)
    for column, (value, label) in enumerate((("{{Trainer}}", "Trainer"), ("{{Date}}", "Date"))):
        for row, (text, bold) in enumerate(((value, True), (label, False))):
            paragraph = table.cell(row, column).paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(text)
            run.font.size = Pt(13 if bold else 10)
            run.bold = bold
            if not bold:
                run.font.color.rgb = grey

    document.save(folder / EXAMPLE_TEMPLATE_NAME)

    people = [
        ["First Name", "Last Name", "Course", "Date", "Trainer", "Certificate No", "Email"],
        ["Priya", "Sharma", "Excel for Beginners", "14 March 2026", "Sam Taylor", "00041", "priya@example.com"],
        ["Tom", "O'Neill", "First Aid at Work", "21 March 2026", "Alex Morgan", "00042", "tom@example.com"],
        ["Mei", "Chen", "Customer Service Skills", "28 March 2026", "Sam Taylor", "00043", "mei@example.com"],
    ]
    # utf-8-sig lets Excel open the file with symbols like é intact
    with open(folder / EXAMPLE_DATA_NAME, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(people)

    print("📝 Your 'mail_merge' folder was empty, so these example files were added:")
    print(f"   {EXAMPLE_TEMPLATE_NAME}  — a certificate with placeholders like {{{{First Name}}}}")
    print(f"   {EXAMPLE_DATA_NAME}     — 3 people to fill it in with (open it in Excel)")
    print("   Type y below to see the result. To use your own files later, delete these")
    print("   two and put your own Word template and spreadsheet in the folder.")
    print()


# --- Asking questions ---------------------------------------------------------

def ask_yes(question: str) -> bool:
    """Ask a yes/no question. Only "y" or "yes" counts as yes."""
    try:
        answer = input(question)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def choose_file(files: list[Path], kind: str, max_tries: int = 3) -> Optional[Path]:
    """
    Pick the file to use. With just one there is nothing to ask; with
    several, show a numbered list. Returns None if no choice was made.
    """
    if len(files) == 1:
        return files[0]

    print(f"Found {len(files)} {kind}s in '{INPUT_FOLDER_NAME}':")
    for number, path in enumerate(files, start=1):
        print(f"   {number}. {path.name}")
    for _ in range(max_tries):
        try:
            answer = input(f"Which {kind} should be used? Type a number (1-{len(files)}): ")
        except EOFError:
            return None
        if answer.strip().isdigit() and 1 <= int(answer) <= len(files):
            print()
            return files[int(answer) - 1]
        print(f"   ⚠️  Please type a number from 1 to {len(files)}.")
    return None


def explain_what_to_add(templates: list[Path], data_files: list[Path], old_word: list[Path]) -> None:
    """Tell the user which file is missing and how to add it."""
    for path in old_word:
        print(f"⚠️  '{path.name}' can't be used as a template. Open it in Word, choose")
        print("   File → Save As, and pick 'Word Document (.docx)'.")
        print()
    if not templates:
        print("No Word template (.docx) found yet.")
    if not data_files:
        print("No spreadsheet (.xlsx, .xls or .csv) found yet.")
    print()
    print("What to do next:")
    print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
    print("  2. Put ONE Word template (.docx) in it. Wherever a person's details should")
    print("     go, type the spreadsheet's column heading in double curly braces,")
    print("     for example:  Dear {{First Name}},")
    print("  3. Put ONE spreadsheet (.xlsx, .xls or .csv) next to it, with the column")
    print("     headings in the first row and one person per row.")
    print("  4. Run this script again:")
    print()
    print("         python mail_merge.py")
    print()


# ---------------------------------------------------------------------------
# Main program — runs when you type: python mail_merge.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Mail-Merge Certificates & Letters")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()

    # 1) Find the template and the spreadsheet
    templates = find_files(input_dir, TEMPLATE_EXTENSIONS)
    data_files = find_files(input_dir, DATA_EXTENSIONS)
    if not templates and not data_files:
        create_example_files(input_dir)
        templates = find_files(input_dir, TEMPLATE_EXTENSIONS)
        data_files = find_files(input_dir, DATA_EXTENSIONS)

    if not templates or not data_files:
        explain_what_to_add(templates, data_files, find_files(input_dir, OLD_WORD_EXTENSIONS))
        return

    template_path = choose_file(templates, "Word template")
    data_path = choose_file(data_files, "spreadsheet") if template_path else None
    if not template_path or not data_path:
        print()
        print("Cancelled — nothing was created.")
        return

    # 2) Read the template and look for placeholders
    try:
        template_bytes = template_path.read_bytes()
        scanner = MergeTemplate(template_bytes)
        scanner.scan()
    except Exception as err:
        print(f"⚠️  Could not open the Word template '{template_path.name}'. Reason: {err}")
        print("   Check it opens in Word, and save it again as a .docx file.")
        print()
        return

    if scanner.problems:
        print(f"⚠️  Stopped: please fix the template '{template_path.name}' first:")
        for problem in dict.fromkeys(scanner.problems):  # each problem once
            print(f"   - {problem}")
        print()
        print("Nothing was created.")
        print()
        return

    if not scanner.found:
        print(f"⚠️  No placeholders were found in '{template_path.name}'.")
        print("   Type the spreadsheet's column headings in double curly braces wherever a")
        print("   person's details should go, for example:  Dear {{First Name}},")
        print("   then save the template and run this script again.")
        print()
        return

    # 3) Read the spreadsheet
    try:
        table, sheet_note = read_spreadsheet(data_path)
    except Exception as err:
        print(f"⚠️  Could not open the spreadsheet '{data_path.name}'. Reason: {err}")
        print("   If it is open in Excel, close it and try again.")
        print()
        return
    if sheet_note:
        print(sheet_note)

    columns = [column_title(c) for c in table.columns]
    # matching key → (column position, heading as typed). If two headings
    # only differ by capitals or spaces, the first one is used.
    column_keys: dict = {}
    for index, title in enumerate(columns):
        if title:
            column_keys.setdefault(match_key(title), (index, title))
    rows, empty_rows = table_to_rows(table)

    if not rows:
        print(f"⚠️  '{data_path.name}' has no rows of data yet — only the headings row.")
        print("   Add one person per row under the headings, then run this script again.")
        print()
        return

    # 4) Show the check and ask before making anything
    if not show_check(template_path, data_path, scanner.found, [c for c in columns if c],
                      column_keys, rows):
        return
    if empty_rows:
        print(f"({empty_rows} completely empty row(s) in the spreadsheet will be skipped.)")

    names = plan_file_names(rows, column_keys)
    unknown = [t for t in PLACEHOLDER_IN_TEXT.findall(FILE_NAME_PATTERN)
               if match_key(t) not in column_keys]
    if unknown:
        print(f"Note: FILE_NAME_PATTERN uses {tidy_placeholder(unknown[0])}, which isn't a column,")
        print("so the documents will be called Document_001, Document_002 ...")
    shown = ", ".join(f"{name}.docx" for name in names[:PREVIEW_NAMES])
    more = " ..." if len(names) > PREVIEW_NAMES else ""
    print(f"Documents will be saved in '{OUTPUT_FOLDER_NAME}', named like:")
    print(f"   {shown}{more}")
    replaced = sum((output_dir / f"{name}.docx").exists() for name in names)
    if replaced:
        print(f"Note: {replaced} file(s) there from an earlier run have the same name and will be replaced.")
    if MAKE_PDFS:
        if find_libreoffice():
            print("PDF copies will also be made with LibreOffice.")
        else:
            print("PDF copies can't be made — LibreOffice isn't installed (see the note at the end).")
    print()

    total = len(rows)
    if not ask_yes(f"Create {total} documents? Type y to continue: "):
        print()
        print("Cancelled — nothing was created.")
        return
    print()

    # 5) Make one document per row
    variable_names = {key: f"col_{index}" for key, (index, _) in column_keys.items()}
    print(f"Making {total} document(s)...")
    made: list[Path] = []
    for count, (row, name) in enumerate(zip(rows, names), start=1):
        destination = output_dir / f"{name}.docx"
        try:
            make_document(template_bytes, variable_names, row, destination)
        except PermissionError:
            print(f"   ⚠️  Skipped row {row.number} — '{destination.name}' is open in another "
                  "program (like Word). Close it and run again.")
            continue
        except Exception as err:
            print(f"   ⚠️  Skipped row {row.number} — Reason: {err}")
            continue
        made.append(destination)
        print(f"   {count} of {total}: {destination.name}")
    print(f"   Done! Made {len(made)} Word document(s).")
    print()

    # 6) Optional PDF copies
    pdf_count = make_pdfs(made, output_dir) if MAKE_PDFS and made else 0

    print("=" * 60)
    pdf_note = f" and {pdf_count} PDF(s)" if pdf_count else ""
    print(f"All done! Made {len(made)} document(s){pdf_note} in the '{OUTPUT_FOLDER_NAME}' folder.")
    if len(made) < total:
        print(f"{total - len(made)} row(s) were skipped — see the ⚠️  messages above.")
    print(f"Your template and spreadsheet in '{INPUT_FOLDER_NAME}' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Scanned Document Reader (OCR)
=============================
This script looks in an "input_scans" folder for scanned PDFs, photos of
documents (letters, receipts, whiteboards) and screenshots. It reads the words
in each one and saves them as a plain text file in "scanned_text" that opens
nicely in Notepad, TextEdit, or Word.

Example: input_scans/receipt.jpg      →  scanned_text/receipt.txt
         input_scans/signed_lease.pdf  →  scanned_text/signed_lease.txt
                                          (with a "----- Page 1 of 4 -----"
                                           line above each page)

Reading words out of a picture is called OCR ("optical character
recognition"). It all happens on YOUR computer — your documents are never
uploaded anywhere, so private paperwork stays private.

Languages: the built-in text model reads English and most languages written
with the Latin alphabet, accents included (French, German, Spanish, Italian,
Portuguese, Dutch, Polish, Turkish, Swedish and more), plus Chinese and
Japanese. It does NOT read Russian/Cyrillic, Greek, Korean, Arabic, Hebrew or
Hindi. Printed text works best; handwriting is often misread.

Your original files are never changed.

How to run (after following README.md):
    python ocr_reader.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in Python tools, plus the OCR and PDF libraries
# ---------------------------------------------------------------------------

import io  # Lets us open files from memory instead of keeping them open on disk
import logging  # Used to hide the OCR library's technical messages
import math  # Square roots, for shrinking huge pictures evenly
import re  # "Regular expressions" — a way to spot text patterns like blank lines
import statistics  # Works out middle values (medians) when tidying the text
import sys  # Gives access to the terminal output settings
import warnings  # Lets us hide a few harmless technical warnings (see below)
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import List, NamedTuple, Optional

# On some Macs, a helper library prints a scary-looking (but harmless) warning
# about "OpenSSL" every time it loads. Reading scans works fine either way,
# so we hide that one message to keep the output easy to read.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

# rapidocr does the actual reading. It runs its text models with onnxruntime.
# pypdfium2 turns each PDF page into a picture, and pypdf checks whether a page
# already contains real (typed) text. Pillow opens photos and screenshots.
try:
    import onnxruntime  # noqa: F401  (not used directly — rapidocr needs it)
    import pypdfium2
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    from pypdf import PdfReader
    from rapidocr import RapidOCR
except ImportError as missing:
    print()
    print("=" * 60)
    if "DLL load failed" in str(missing):
        # Windows only: onnxruntime is installed but needs a free Microsoft
        # helper package that some computers don't have yet.
        print("Oops! The OCR library is installed, but Windows is missing")
        print("a free Microsoft helper it needs. Download and install the")
        print("'Microsoft Visual C++ Redistributable' (x64) from:")
        print()
        print("    https://aka.ms/vs/17/release/vc_redist.x64.exe")
        print()
        print("Then restart your computer and run this script again.")
    else:
        print("Oops! The OCR (text recognition) libraries are not installed yet.")
        print("Open your terminal in this project folder and run:")
        print()
        print("    pip install -r requirements.txt")
        print()
        print("Or install just what this tool needs:")
        print()
        print("    pip install rapidocr onnxruntime pypdfium2 pypdf Pillow")
        print()
        print("Then run this script again. See README.md for full steps.")
    print(f"(Technical details: {missing})")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the scans, photos and screenshots
INPUT_FOLDER_NAME = "input_scans"

# Folder where THIS SCRIPT saves the text files
OUTPUT_FOLDER_NAME = "scanned_text"

# File endings we accept as input (case-insensitive).
# iPhone photos (.heic) aren't supported — see the guide for a quick fix.
PDF_EXTENSIONS = {".pdf"}
PICTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
ALLOWED_EXTENSIONS = PDF_EXTENSIONS | PICTURE_EXTENSIONS

# How sharp each PDF page is when we turn it into a picture to read it,
# in "dots per inch" (DPI):
#   150 — faster, but small print (footnotes, receipts) may be misread
#   200 — good balance for normal letters and forms (the default)
#   300 — sharpest for tiny print, but about twice as slow and uses more memory
PDF_DPI = 200

# Very big pictures (e.g. 48-megapixel phone photos) are shrunk to about this
# many megapixels before reading. That's still plenty sharp for text, and it
# keeps the script fast and stops it running out of memory.
MAX_PICTURE_MEGAPIXELS = 12

# The OCR gives every piece of text a confidence score from 0 (a wild guess)
# to 1 (completely sure). Pieces below this score are left out, because they
# are usually smudges, patterns or background clutter rather than real words.
# Lower it (e.g. 0.3) to keep more doubtful words; raise it (e.g. 0.7) to keep
# only words the OCR is sure about.
MIN_CONFIDENCE = 0.5

# If a PDF page already contains at least this many letters/digits of real,
# typed text, we copy that text exactly instead of using OCR (it's perfect and
# instant). Pages with less — say just a page number — are read with OCR.
MIN_REAL_TEXT_CHARACTERS = 20

# Rebuilding the lines and paragraphs. Distances are measured in "text heights"
# (the height of one line of letters), so they work for any size of writing.
SAME_LINE_TOLERANCE = 0.5  # Pieces this close vertically are on the same line
PARAGRAPH_GAP = 1.0  # An empty gap at least this tall starts a new paragraph
WIDE_GAP = 2.5  # A sideways gap this wide (e.g. "Coffee ...... 3.50") keeps
WIDE_GAP_SPACES = "    "  # a few spaces, so receipts and forms stay readable

# Average confidence needed for each "reading quality" label in the summary
CLEAR_QUALITY = 0.90
FAIR_QUALITY = 0.75

# Rough size of the text model, shown if it ever needs to be downloaded
MODEL_DOWNLOAD_SIZE = "32 MB"

# Invisible "control characters" that some PDFs contain. They show up as
# little boxes or garbage in Notepad, so we remove them.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Four or more line breaks in a row = three or more empty lines. We squeeze
# those down to a single empty line so the text file isn't full of gaps.
TOO_MANY_BLANK_LINES = re.compile(r"\n{4,}")

# pdfium's error number for "this PDF needs a password"
PDFIUM_PASSWORD_ERROR = 4


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class SkipThisFile(Exception):
    """Raised with a friendly explanation when a file can't be processed."""


class TextPiece(NamedTuple):
    """
    One piece of text the OCR found (usually a word or a short phrase),
    plus where it sits in the picture, measured in pixels from the top-left.
    """

    text: str
    confidence: float  # 0 = wild guess, 1 = completely sure
    left: float  # x position of its left edge
    right: float  # x position of its right edge
    middle: float  # y position of its middle
    height: float  # how tall the letters are
    tilt: float  # how much it slopes: 0 = level, 0.1 = goes down 1 px every 10 px


class PageResult(NamedTuple):
    """What we found on one page (or one picture)."""

    text: str
    pieces: List[TextPiece]  # The OCR pieces kept (empty for copied PDF text)
    left_out: int  # Pieces dropped for being below MIN_CONFIDENCE
    copied_real_text: bool  # True if the PDF already had typed text we copied


class DownloadWatcher(logging.Handler):
    """
    Listens to the OCR library's messages and notices if it starts
    downloading its text model, so we can explain the wait in plain English.
    """

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.downloaded = False

    def emit(self, record: logging.LogRecord) -> None:
        if self.downloaded or "download" not in record.getMessage().lower():
            return
        self.downloaded = True
        print(f"   First run: downloading the text recognition model (about {MODEL_DOWNLOAD_SIZE}).")
        print("   This happens only once. Only the model is downloaded — your")
        print("   documents are NOT uploaded. After this, reading works fully offline.")


def ensure_folders() -> tuple[Path, Path]:
    """
    Make sure the input and output folders exist.
    Returns (input_path, output_path).
    """
    # Path(".") means "the folder where you ran the script from"
    project_root = Path(".")

    input_dir = project_root / INPUT_FOLDER_NAME
    output_dir = project_root / OUTPUT_FOLDER_NAME

    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {input_dir.resolve()}")
        print("   → Put your scans, photos or screenshots in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_files(input_dir: Path) -> tuple[list[Path], list[Path]]:
    """
    Look inside the input folder (not subfolders).
    Returns (files we can read, files of a type we can't read).
    """
    readable, unsupported = [], []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._scan.pdf"
        # copies macOS leaves on USB drives, and Windows' own system files.
        if item.name.startswith(".") or not item.is_file():
            continue
        if item.name.lower() in {"desktop.ini", "thumbs.db"}:
            continue
        if item.suffix.lower() in ALLOWED_EXTENSIONS:
            readable.append(item)
        else:
            unsupported.append(item)

    # Sort alphabetically so "file 1 of 5" feels predictable
    def by_name(path: Path) -> str:
        return path.name.lower()

    return sorted(readable, key=by_name), sorted(unsupported, key=by_name)


def explain_unsupported(files: list[Path]) -> None:
    """Tell the user which files were ignored, with a tip for iPhone photos."""
    names = ", ".join(path.name for path in files[:5])
    if len(files) > 5:
        names += f" and {len(files) - 5} more"
    print(f"Note: ignored {len(files)} file(s) this tool can't read: {names}")
    if any(path.suffix.lower() in {".heic", ".heif"} for path in files):
        print("   iPhone .heic photos: open them and export/share as JPEG, or set")
        print("   Settings → Camera → Formats → 'Most Compatible' on the iPhone.")
    print()


def print_problem_box(lines: list[str]) -> None:
    """Print an important message inside a box of '=' signs so it stands out."""
    print()
    print("=" * 60)
    for line in lines:
        print(line)
    print("=" * 60)
    print()


def load_ocr_engine() -> RapidOCR:
    """
    Load the text recognition model once for the whole batch.

    The model normally comes included with rapidocr, so nothing needs to be
    downloaded. If its files are missing or damaged, rapidocr downloads them
    once (from modelscope.cn) and keeps them for next time.
    """
    print("Loading the text recognition model...")

    # rapidocr prints lots of technical log lines. We hide them, but keep
    # listening so we can explain a first-time download in plain English.
    ocr_log = logging.getLogger("RapidOCR")
    for handler in ocr_log.handlers:
        handler.setLevel(logging.CRITICAL)
    watcher = DownloadWatcher()
    ocr_log.addHandler(watcher)

    try:
        engine = RapidOCR(
            params={
                "Global.log_level": "info",  # So the download watcher hears everything
                # We filter by MIN_CONFIDENCE ourselves, so we can count what was left out
                "Global.text_score": 0.0,
                # We already shrink huge pictures ourselves (MAX_PICTURE_MEGAPIXELS).
                # This stops rapidocr shrinking them further, which blurs small print.
                "Global.max_side_len": 100_000,
            }
        )
        # The model has three parts (find text, turn it upright, read it).
        # Load them all now rather than on the first file, so any one-time
        # download happens here, before reading starts.
        for part in ("_load_det_model", "_load_cls_model", "_load_rec_model"):
            if hasattr(engine, part):
                getattr(engine, part)()
    except Exception as err:
        if watcher.downloaded:
            print_problem_box([
                "Oops! The text recognition model could not be downloaded.",
                f"It's needed once (about {MODEL_DOWNLOAD_SIZE}); after that, no internet is needed.",
                "",
                "What to try:",
                "  1. Check your internet connection (or Wi-Fi sign-in page).",
                "  2. On a work network, a firewall may block modelscope.cn —",
                "     try another network, such as home Wi-Fi.",
                "  3. Or reinstall rapidocr, which includes the model:",
                "         pip install --force-reinstall rapidocr",
                "  Nothing was read yet, and your files were not changed.",
                "",
                f"Technical details: {err}",
            ])
        else:
            print_problem_box([
                "Oops! The text recognition model could not be loaded.",
                "Try reinstalling the OCR libraries, then run this script again:",
                "",
                "    pip install --force-reinstall rapidocr onnxruntime",
                "",
                f"Technical details: {err}",
            ])
        raise SystemExit(1)
    finally:
        ocr_log.removeHandler(watcher)

    if watcher.downloaded:
        print("   Ready! Model downloaded and saved for next time.")
    else:
        print("   Ready! (found on this computer — no internet needed)")
    print()
    return engine


def clean_text(raw: str) -> str:
    """
    Tidy up text so it reads well in Notepad:
      - use one kind of line break everywhere
      - remove invisible control characters
      - remove spaces at the end of lines
      - squeeze 3+ empty lines in a row down to one empty line
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARACTERS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = TOO_MANY_BLANK_LINES.sub("\n\n", text)
    # Drop empty lines at the very start and end
    return text.strip("\n")


def make_piece(box, text: str, confidence: float) -> TextPiece:
    """
    Turn one OCR result into a TextPiece.

    The OCR describes where it found the text with 4 corner points, in the
    order: top-left, top-right, bottom-right, bottom-left. The box can be
    slightly tilted if the page was photographed or scanned at an angle.
    """
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = [(float(x), float(y)) for x, y in box]
    left_middle = (y1 + y4) / 2  # Middle of the left edge
    right_middle = (y2 + y3) / 2  # Middle of the right edge
    left = min(x1, x4)
    right = max(x2, x3)
    width = max(right - left, 1.0)
    return TextPiece(
        text=text.strip(),
        confidence=float(confidence),
        left=left,
        right=right,
        middle=(left_middle + right_middle) / 2,
        # Average of the left and right edge lengths
        height=max((math.dist((x1, y1), (x4, y4)) + math.dist((x2, y2), (x3, y3))) / 2, 1.0),
        tilt=(right_middle - left_middle) / width,
    )


def page_tilt(pieces: list[TextPiece]) -> float:
    """
    Work out how much the whole page is tilted, from the slope of its longer
    pieces of text (short ones like "a" or "5" give unreliable slopes).
    We take the middle value, so one odd piece can't throw it off.
    """
    slopes = [p.tilt for p in pieces if p.right - p.left >= 2 * p.height]
    if not slopes:
        return 0.0
    # Ignore anything steeper than ~15 degrees — that's not a tilted page
    return max(-0.27, min(0.27, statistics.median(slopes)))


def arrange_into_lines(pieces: list[TextPiece]) -> list[list[TextPiece]]:
    """
    Put the pieces in natural reading order: lines from top to bottom, and
    pieces within each line from left to right.

    If the page is tilted, a line drifts up or down as it goes across. So we
    first "straighten" each piece's position by the page's tilt, then group
    pieces whose straightened middles are within SAME_LINE_TOLERANCE text
    heights of each other.
    """
    if not pieces:
        return []
    tilt = page_tilt(pieces)

    def straightened(piece: TextPiece) -> float:
        centre_x = (piece.left + piece.right) / 2
        return piece.middle - tilt * centre_x

    lines: list[list[TextPiece]] = []
    line_middles: list[float] = []  # Average straightened middle of each line

    for piece in sorted(pieces, key=straightened):
        position = straightened(piece)
        best_line, best_distance = None, None
        for number, line in enumerate(lines):
            distance = abs(position - line_middles[number])
            line_height = statistics.median(p.height for p in line)
            if distance > SAME_LINE_TOLERANCE * min(piece.height, line_height):
                continue
            if best_distance is None or distance < best_distance:
                best_line, best_distance = number, distance
        if best_line is None:
            lines.append([piece])
            line_middles.append(position)
        else:
            lines[best_line].append(piece)
            members = lines[best_line]
            line_middles[best_line] = sum(straightened(p) for p in members) / len(members)

    # Top-to-bottom, then left-to-right within each line
    order = sorted(range(len(lines)), key=lambda number: line_middles[number])
    return [sorted(lines[number], key=lambda p: p.left) for number in order]


def lines_to_text(lines: list[list[TextPiece]]) -> str:
    """
    Join the lines into text. Pieces on a line are separated by a space (or a
    few spaces if there's a wide gap). A big empty gap between two lines
    starts a new paragraph (an empty line), like in the original.
    """
    if not lines:
        return ""
    typical_height = statistics.median(p.height for line in lines for p in line)
    tilt = page_tilt([p for line in lines for p in line])

    def top_and_bottom(line: list[TextPiece]) -> tuple[float, float]:
        tops = [p.middle - tilt * (p.left + p.right) / 2 - p.height / 2 for p in line]
        bottoms = [p.middle - tilt * (p.left + p.right) / 2 + p.height / 2 for p in line]
        return min(tops), max(bottoms)

    output: list[str] = []
    previous_bottom = None
    for line in lines:
        top, bottom = top_and_bottom(line)
        if previous_bottom is not None and top - previous_bottom >= PARAGRAPH_GAP * typical_height:
            output.append("")  # Empty line = new paragraph

        words = line[0].text
        for before, piece in zip(line, line[1:]):
            gap = piece.left - before.right
            words += WIDE_GAP_SPACES if gap >= WIDE_GAP * typical_height else " "
            words += piece.text
        output.append(words)
        previous_bottom = bottom

    return clean_text("\n".join(output))


def read_picture(engine: RapidOCR, picture: Image.Image) -> PageResult:
    """Run OCR on one picture and rebuild its text in reading order."""
    result = engine(picture)
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or not texts:
        return PageResult("", [], 0, False)  # No text at all (blank page or photo)

    pieces = [make_piece(box, text, score) for box, text, score in zip(boxes, texts, scores)]
    kept = [p for p in pieces if p.text and p.confidence >= MIN_CONFIDENCE]
    left_out = sum(1 for p in pieces if p.text and p.confidence < MIN_CONFIDENCE)
    return PageResult(lines_to_text(arrange_into_lines(kept)), kept, left_out, False)


def prepare_picture(picture: Image.Image) -> Image.Image:
    """
    Get a photo or scan ready for reading:
      - turn it the right way up (phones save "rotate me" notes in the photo)
      - put see-through screenshots on a white background
      - fix very dark 16-bit scans, and convert everything to normal colours
      - shrink huge pictures to about MAX_PICTURE_MEGAPIXELS
    """
    try:
        picture = ImageOps.exif_transpose(picture)
    except Exception:
        picture = picture.copy()  # Damaged "rotate me" note — read it as it is

    if picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info:
        # See-through areas would otherwise turn black — and so would black text
        background = Image.new("RGBA", picture.size, "white")
        picture = Image.alpha_composite(background, picture.convert("RGBA"))
    elif picture.mode.startswith("I") or picture.mode == "F":
        # Some scanners save extra-detailed (16-bit) greys. A normal conversion
        # would turn almost everything white, so we scale the greys down first.
        picture = picture.convert("F")
        darkest, brightest = picture.getextrema()
        if brightest > 255:
            picture = picture.point(lambda value: value * 255 / brightest)
    picture = picture.convert("RGB")

    max_pixels = MAX_PICTURE_MEGAPIXELS * 1_000_000
    width, height = picture.size
    if width * height > max_pixels:
        scale = math.sqrt(max_pixels / (width * height))
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        picture = picture.resize(new_size, Image.Resampling.LANCZOS)
    return picture


def open_pictures(source: Path) -> list[Image.Image]:
    """
    Open a photo, screenshot or scan. Returns one picture per page — normally
    just one, but a .tif from a scanner or fax can hold several pages.
    """
    try:
        # Read the whole file into memory first, so the original is never
        # held open (Windows won't complain the file is "in use").
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source.read_bytes())) as opened:
                width, height = opened.size
                max_pixels = MAX_PICTURE_MEGAPIXELS * 1_000_000
                if opened.format == "JPEG" and width * height > max_pixels:
                    # Big JPEGs can be decoded at a smaller size directly,
                    # which is much faster and uses less memory.
                    scale = math.sqrt(max_pixels / (width * height))
                    opened.draft("RGB", (round(width * scale), round(height * scale)))
                if opened.format == "TIFF":
                    frames = ImageSequence.Iterator(opened)
                else:
                    frames = [opened]
                return [prepare_picture(frame) for frame in frames]
    except Image.DecompressionBombError as err:
        raise SkipThisFile(
            "this picture is far too big to open safely. Shrink it in a photo "
            "editor (to under about 50 megapixels) and try again."
        ) from err
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as err:
        raise SkipThisFile(
            "this file could not be opened as a picture. It may be damaged, only "
            "partly downloaded, or not really a picture (just renamed). "
            f"Technical details: {err}"
        ) from err


def open_pdf(source: Path) -> tuple[pypdfium2.PdfDocument, list[str]]:
    """
    Open a PDF for reading. Returns the PDF (to turn pages into pictures) and
    the real typed text already on each page ("" for pages without any).
    """
    data = source.read_bytes()
    try:
        # A blank password is tried automatically, so PDFs that are only
        # locked against editing or printing open fine.
        pdf = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as err:
        if getattr(err, "err_code", None) == PDFIUM_PASSWORD_ERROR or "password" in str(err).lower():
            raise SkipThisFile(
                "this PDF is password-protected. Open it with its password, "
                "save or 'Print to PDF' a copy without a password, put that copy "
                f"in '{INPUT_FOLDER_NAME}', and run the script again."
            ) from err
        raise SkipThisFile(
            "this file could not be opened as a PDF. It may be damaged, only "
            "partly downloaded, or not really a PDF (just renamed to .pdf). "
            f"Technical details: {err}"
        ) from err

    return pdf, read_real_text(data, len(pdf))


def read_real_text(data: bytes, page_count: int) -> list[str]:
    """
    Get any real typed text from each page with pypdf. Scanned pages have
    none. If pypdf can't read the file, we simply OCR every page instead.
    """
    no_text = [""] * page_count
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return no_text
        if len(reader.pages) != page_count:
            return no_text
        texts = []
        for page in reader.pages:
            try:
                texts.append(clean_text(page.extract_text() or ""))
            except Exception:
                texts.append("")  # One odd page shouldn't stop the others
        return texts
    except Exception:
        # e.g. strong (AES) protection needing an extra library — the page
        # pictures still work, so OCR will read them.
        return no_text


def has_real_text(text: str) -> bool:
    """True if the page has enough typed text to copy instead of using OCR."""
    letters_and_digits = sum(1 for character in text if character.isalnum())
    return letters_and_digits >= MIN_REAL_TEXT_CHARACTERS


def render_page(pdf: pypdfium2.PdfDocument, index: int) -> Image.Image:
    """Turn one PDF page into a picture at PDF_DPI (smaller for huge pages)."""
    page = pdf[index]
    try:
        width_points, height_points = page.get_size()  # 72 points = 1 inch
        scale = PDF_DPI / 72
        max_pixels = MAX_PICTURE_MEGAPIXELS * 1_000_000
        if width_points * height_points * scale * scale > max_pixels:
            # A poster-sized page: lower the DPI so the picture isn't enormous
            scale = math.sqrt(max_pixels / (width_points * height_points))
        return page.render(scale=scale).to_pil().convert("RGB")
    finally:
        page.close()


def read_pdf(engine: RapidOCR, source: Path) -> list[PageResult]:
    """Read every page of a PDF, showing progress for multi-page files."""
    pdf, real_texts = open_pdf(source)
    try:
        total = len(pdf)
        if total == 0:
            raise SkipThisFile("this PDF has no pages.")
        results = []
        for index in range(total):
            progress = f"   Reading page {index + 1} of {total}..."
            real_text = real_texts[index]

            if has_real_text(real_text):
                if total > 1:
                    print(f"{progress} (already has real text — copied it exactly)", flush=True)
                results.append(PageResult(real_text, [], 0, True))
                continue

            if total > 1:
                # flush=True shows the line immediately instead of waiting
                print(progress, flush=True)
            try:
                results.append(read_picture(engine, render_page(pdf, index)))
            except Exception as err:
                # One odd page shouldn't stop the rest of the document
                print(f"   ⚠️  Could not read page {index + 1} — skipped it. ({err})")
                results.append(PageResult("", [], 0, False))
        return results
    finally:
        pdf.close()


def read_picture_file(engine: RapidOCR, source: Path) -> list[PageResult]:
    """Read a photo, screenshot or (possibly multi-page) scanned picture."""
    pictures = open_pictures(source)
    total = len(pictures)
    results = []
    for number, picture in enumerate(pictures, start=1):
        if total > 1:
            print(f"   Reading page {number} of {total}...", flush=True)
        results.append(read_picture(engine, picture))
    return results


def average_confidence(pages: list[PageResult]) -> Optional[float]:
    """
    The OCR's average confidence, giving longer pieces of text more weight.
    None if no page was read with OCR (e.g. all text was copied from the PDF).
    """
    pieces = [piece for page in pages for piece in page.pieces]
    total_letters = sum(len(piece.text) for piece in pieces)
    if not total_letters:
        return None
    return sum(piece.confidence * len(piece.text) for piece in pieces) / total_letters


def describe_quality(confidence: Optional[float]) -> str:
    """Turn the average confidence into a friendly 'reading quality' hint."""
    if confidence is None:
        return "✓ exact (copied from the PDF's own text — no OCR needed)"
    # Shown as at most 99%: OCR is never completely certain
    percent = f"average confidence {min(confidence, 0.99):.0%}"
    if confidence >= CLEAR_QUALITY:
        return f"✓ clear ({percent})"
    if confidence >= FAIR_QUALITY:
        return f"fair ({percent}) — a few words may be wrong; check names and numbers"
    return f"⚠️  poor ({percent}) — some words may be wrong — check the original"


def build_text_file(source_name: str, pages: list[PageResult]) -> str:
    """
    Build the finished text file: a short header, then the text. Files with
    more than one page get a clear "----- Page 1 of 3 -----" line above each.
    """
    total = len(pages)
    header = f"Text read from: {source_name}\nPages: {total}"
    if any(not page.copied_real_text for page in pages):
        header += (
            "\nRead by OCR (text recognition) — check names, numbers and amounts "
            "against the original."
        )
    parts = [header]

    if total == 1:
        parts.append(pages[0].text)
    else:
        for number, page in enumerate(pages, start=1):
            parts.append(f"----- Page {number} of {total} -----")
            parts.append(page.text if page.text else "[No text found on this page]")

    # An empty line between sections keeps the file easy to scan by eye
    return "\n\n".join(parts) + "\n"


def choose_destination(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick an output filename that won't silently overwrite another text file
    from the *same* run. Re-running the script replaces older results.

    Normal case:  receipt.jpg  →  receipt.txt
    Name clash:   receipt.pdf also in this batch  →  receipt_pdf.txt
    (Windows and macOS treat "Receipt" and "receipt" as the same name.)
    """
    # Windows dislikes file names ending in a space or dot, so trim those
    stem = source.stem.strip(" .") or "scan"
    candidates = [stem, f"{stem}_{source.suffix.lower().lstrip('.')}"]
    counter = 2
    while True:
        for name in candidates:
            if name.lower() not in used_names:
                used_names.add(name.lower())
                return output_dir / f"{name}.txt"
        candidates = [f"{stem}_{counter}"]
        counter += 1


def read_one_file(
    engine: RapidOCR,
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
) -> None:
    """Read one file, save its text, and print a short summary."""
    print(f"Reading file {index} of {total}: {source.name} ...")

    try:
        if source.suffix.lower() in PDF_EXTENSIONS:
            pages = read_pdf(engine, source)
        else:
            pages = read_picture_file(engine, source)
    except SkipThisFile as reason:
        print(f"   ⚠️  Skipped this file — {reason}")
        print()
        return
    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — something went wrong: {err}")
        print()
        return

    print(f"   Pages: {len(pages)}")

    all_text = "\n".join(page.text for page in pages)
    if not all_text.strip():
        print("   ⚠️  No text found — it looks blank, or the writing is too small,")
        print("      faint or blurry to read. Nothing was saved for this file.")
        print()
        return

    destination = choose_destination(source, output_dir, used_names)
    # UTF-8 keeps accents, symbols and other languages intact
    destination.write_text(build_text_file(source.name, pages), encoding="utf-8")

    print(f"   Words found: {len(all_text.split()):,}")
    copied = sum(1 for page in pages if page.copied_real_text)
    if copied:
        print(
            f"   {copied} of {len(pages)} page(s) already had real text — "
            "copied it exactly (no OCR needed)."
        )
    empty_pages = sum(1 for page in pages if not page.text)
    if empty_pages:
        print(f"   Note: {empty_pages} page(s) had no readable text (blank pages?).")
    left_out = sum(page.left_out for page in pages)
    if left_out:
        print(f"   Left out {left_out} unclear fragment(s) (below MIN_CONFIDENCE).")
    print(f"   Reading quality: {describe_quality(average_confidence(pages))}")
    print(f"   Done! Saved as: {destination.name}")
    print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python ocr_reader.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    # pypdf prints technical warnings about slightly messy (but readable)
    # PDFs. They aren't useful to most people, so we only show real errors.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Scanned Document Reader (OCR)")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    files, unsupported = find_files(input_dir)

    if unsupported:
        explain_unsupported(unsupported)

    if not files:
        print("No scans, photos or screenshots found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your scanned PDFs, photos or screenshots into it")
        print("     (.pdf / .jpg / .jpeg / .png / .tif / .tiff / .bmp / .webp).")
        print("  3. Run this script again:")
        print()
        print("         python ocr_reader.py")
        print()
        return

    total = len(files)
    print(f"Found {total} file(s) to read.")
    print()

    # Loading the model takes a moment, so we do it once for the whole batch
    # instead of once per file.
    engine = load_ocr_engine()

    # Track names already used this run so receipt.jpg and receipt.pdf
    # don't overwrite each other's text.
    used_names: set[str] = set()

    for i, source in enumerate(files, start=1):
        read_one_file(engine, source, output_dir, i, total, used_names)

    print("=" * 60)
    print(f"All done! Check the '{OUTPUT_FOLDER_NAME}' folder for your .txt files.")
    print(f"Originals in '{INPUT_FOLDER_NAME}' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

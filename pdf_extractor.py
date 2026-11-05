#!/usr/bin/env python3
"""
PDF Text & Image Extractor
==========================
This script looks in an "input_pdfs" folder for PDF files. For every PDF it
finds, it makes a new folder inside "extracted_pdfs" containing:

  1. A plain text file (.txt) with all the words from the PDF, page by page,
     that opens nicely in Notepad, TextEdit, or Word
  2. An "images" folder with every picture inside the PDF (only if it has any).
     Pictures that appear more than once — like a logo on every page — are
     saved only once.

Example: input_pdfs/report.pdf  →  extracted_pdfs/report/report.txt
                                   extracted_pdfs/report/images/page01_image01.png

Your original PDFs are never changed.

How to run (after following README.md):
    python pdf_extractor.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in Python tools, plus pypdf (and Pillow) for PDF work
# ---------------------------------------------------------------------------

import hashlib  # Makes a "fingerprint" of each picture to spot exact duplicates
import io  # Lets us hand the PDF to pypdf from memory instead of from disk
import logging  # Used only to hide pypdf's technical warnings from the screen
import re  # "Regular expressions" — a way to spot text patterns like blank lines
import sys  # Gives access to the terminal output settings
from pathlib import Path  # Easy, cross-platform file and folder paths

# pypdf reads the PDF. It quietly uses Pillow to turn the pictures it finds
# into normal image files, so both need to be installed.
try:
    from pypdf import PdfReader
    from pypdf.errors import DependencyError
    import PIL  # noqa: F401  (not used directly — pypdf needs it for pictures)
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The pypdf or Pillow library is not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install -r requirements.txt")
    print()
    print("Or install just the PDF tools:")
    print()
    print("    pip install pypdf Pillow")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the original PDF files
INPUT_FOLDER_NAME = "input_pdfs"

# Folder where THIS SCRIPT saves the text and pictures (one subfolder per PDF)
OUTPUT_FOLDER_NAME = "extracted_pdfs"

# Name of the subfolder (inside each PDF's folder) that holds its pictures
IMAGES_FOLDER_NAME = "images"

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".pdf"}

# Invisible "control characters" that some PDFs contain. They show up as
# little boxes or garbage in Notepad, so we remove them. Normal line breaks
# and tabs are kept.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Four or more line breaks in a row = three or more empty lines. We squeeze
# those down to a single empty line so the text file isn't full of gaps.
TOO_MANY_BLANK_LINES = re.compile(r"\n{4,}")

# The names this script gives to pictures, e.g. "page03_image01.png".
# Used to tidy up pictures left over from an earlier run (and nothing else).
OUR_IMAGE_NAME = re.compile(r"^page\d+_image\d+\.\w+$")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class SkipThisPdf(Exception):
    """Raised with a friendly explanation when a PDF can't be processed."""


class ImageResults:
    """Running totals while saving the pictures from one PDF."""

    def __init__(self) -> None:
        self.saved = 0  # Pictures written to disk
        self.duplicates = 0  # Exact copies we skipped (same picture seen before)
        self.unreadable = 0  # Pictures pypdf could not turn into an image file


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
        print("   → Put your PDF files in this folder, then run the script again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_pdfs(input_dir: Path) -> list[Path]:
    """Return a sorted list of PDF files inside the input folder (not subfolders)."""
    pdfs = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._report.pdf"
        # copies macOS leaves on USB drives — they are not real PDFs.
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            pdfs.append(item)

    # Sort alphabetically so "PDF 1 of 5" feels predictable
    return sorted(pdfs, key=lambda p: p.name.lower())


def open_pdf(source: Path) -> PdfReader:
    """
    Open a PDF and unlock it if it has a blank password.

    Many PDFs are "locked" only against editing or printing, with no password
    needed to open them. Those open fine. If a real password is needed to
    open the file, we stop with a friendly explanation instead.
    """
    try:
        # Read the whole file into memory first. pypdf then never touches the
        # original on disk, and Windows won't complain the file is "in use".
        reader = PdfReader(io.BytesIO(source.read_bytes()))
    except Exception as err:
        raise SkipThisPdf(
            "this file could not be opened as a PDF. It may be damaged, only "
            "partly downloaded, or not really a PDF (just renamed to .pdf). "
            f"Technical details: {err}"
        ) from err

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except DependencyError as err:
            raise SkipThisPdf(needs_cryptography_message()) from err
        except Exception as err:
            raise SkipThisPdf(
                f"this PDF uses a type of protection we can't open. Details: {err}"
            ) from err

        # decrypt() returns 0 ("not decrypted") when the blank password didn't work
        if not unlocked:
            raise SkipThisPdf(
                "this PDF is password-protected. Open it with its password, "
                "save or 'Print to PDF' a copy without a password, put that copy "
                f"in '{INPUT_FOLDER_NAME}', and run the script again."
            )
        print("   This PDF was locked with a blank password — opened it anyway.")

    return reader


def needs_cryptography_message() -> str:
    """Explain the one extra install needed for PDFs with strong (AES) protection."""
    return (
        "this PDF uses strong (AES) protection, and opening it needs one extra "
        "helper library. Run:  pip install cryptography  — then run the script again."
    )


def clean_page_text(raw: str) -> str:
    """
    Tidy up the text from one page so it reads well in Notepad:
      - use one kind of line break everywhere
      - remove invisible control characters
      - remove spaces at the end of lines
      - squeeze 3+ empty lines in a row down to one empty line
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARACTERS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = TOO_MANY_BLANK_LINES.sub("\n\n", text)
    # Drop empty lines at the very start and end of the page
    return text.strip("\n")


def extract_page_texts(reader: PdfReader) -> list[str]:
    """
    Pull the text out of every page. Returns one cleaned string per page
    (an empty string means no text was found on that page).
    """
    page_texts = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except DependencyError:
            # Not a problem with this page — the whole PDF needs an extra
            # library, so let the caller explain that once.
            raise
        except Exception as err:
            # One odd page shouldn't stop the rest of the document
            print(f"   ⚠️  Could not read the text on page {page_number} — skipped it. ({err})")
            raw = ""
        page_texts.append(clean_page_text(raw))
    return page_texts


def build_text_file(pdf_name: str, page_texts: list[str]) -> str:
    """Join the pages into one document with a clear header above each page."""
    total = len(page_texts)
    parts = [f"Text extracted from: {pdf_name}\nPages: {total}"]

    if not any(page_texts):
        parts.append(
            "No text could be found in this PDF. It is probably a scanned "
            "document (photos of pages), which needs OCR (text recognition) "
            "software to turn it into text."
        )

    for page_number, text in enumerate(page_texts, start=1):
        parts.append(f"----- Page {page_number} of {total} -----")
        parts.append(text if text else "[No text found on this page]")

    # An empty line between sections keeps the file easy to scan by eye
    return "\n\n".join(parts) + "\n"


def remove_old_images(images_dir: Path) -> None:
    """
    Delete pictures this script saved on an earlier run, so old and new
    pictures don't get mixed up. Only files named like "page01_image01.png"
    are removed — anything else you put in the folder is left alone.
    """
    if not images_dir.is_dir():
        return
    for item in images_dir.iterdir():
        if item.is_file() and OUR_IMAGE_NAME.match(item.name):
            item.unlink()


def save_images(reader: PdfReader, images_dir: Path) -> ImageResults:
    """
    Save every picture in the PDF into images_dir, skipping exact duplicates.

    Names look like page03_image01.png: the page it was found on, then its
    position on that page. The file ending (.png, .jpg, ...) is whatever
    pypdf says suits that picture best.
    """
    results = ImageResults()
    seen_fingerprints: set[str] = set()

    # Pad page numbers with zeros (01, 02 ... or 001 for long PDFs) so the
    # files sort in the right order in File Explorer / Finder.
    page_digits = max(2, len(str(len(reader.pages))))

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            image_keys = list(page.images.keys())
        except DependencyError:
            raise
        except Exception as err:
            print(f"   ⚠️  Could not look for pictures on page {page_number} — skipped it. ({err})")
            continue

        for position, key in enumerate(image_keys, start=1):
            try:
                # This is the moment pypdf actually decodes the picture
                image = page.images[key]
                data = image.data
            except DependencyError:
                raise
            except Exception as err:
                results.unreadable += 1
                print(
                    f"   ⚠️  Could not read picture {position} on page {page_number} "
                    f"— skipped it. ({err})"
                )
                continue

            # Identical bytes = identical picture (e.g. a logo on every page)
            fingerprint = hashlib.sha256(data).hexdigest()
            if fingerprint in seen_fingerprints:
                results.duplicates += 1
                continue
            seen_fingerprints.add(fingerprint)

            extension = Path(image.name).suffix.lower() or ".png"
            filename = f"page{page_number:0{page_digits}d}_image{position:02d}{extension}"

            # Only create the images folder once we have something to put in it
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / filename).write_bytes(data)
            results.saved += 1

    return results


def choose_output_folder(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick the folder name for one PDF's results.

    Normal case:  report.pdf  →  extracted_pdfs/report/
    Name clash:   Report.PDF also in this batch  →  extracted_pdfs/Report_2/
    (Windows and macOS treat "report" and "Report" as the same folder.)
    """
    # Windows dislikes folder names ending in a space or dot, so trim those
    base = source.stem.strip(" .") or "pdf"
    name = base
    counter = 2
    while name.lower() in used_names:
        name = f"{base}_{counter}"
        counter += 1
    used_names.add(name.lower())
    return output_dir / name


def process_one_pdf(
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
) -> None:
    """Open one PDF, save its text and pictures, and print a short summary."""
    print(f"Extracting PDF {index} of {total}: {source.name} ...")

    try:
        reader = open_pdf(source)
        page_count = len(reader.pages)

        page_texts = extract_page_texts(reader)
        all_text = "\n".join(page_texts)

        pdf_folder = choose_output_folder(source, output_dir, used_names)
        pdf_folder.mkdir(parents=True, exist_ok=True)

        text_file = pdf_folder / f"{pdf_folder.name}.txt"
        # UTF-8 keeps accents, symbols and other languages intact
        with open(text_file, "w", encoding="utf-8") as handle:
            handle.write(build_text_file(source.name, page_texts))

        images_dir = pdf_folder / IMAGES_FOLDER_NAME
        remove_old_images(images_dir)
        images = save_images(reader, images_dir)
        # Don't leave an empty "images" folder behind from an earlier run
        if images_dir.is_dir() and not any(images_dir.iterdir()):
            images_dir.rmdir()

    except SkipThisPdf as reason:
        print(f"   ⚠️  Skipped this file — {reason}")
        print()
        return
    except DependencyError:
        print(f"   ⚠️  Skipped this file — {needs_cryptography_message()}")
        print()
        return
    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — something went wrong: {err}")
        print()
        return

    word_count = len(all_text.split())
    character_count = len(all_text)
    print(f"   Pages: {page_count}")

    if word_count:
        print(f"   Text: {word_count:,} words ({character_count:,} characters)")
        empty_pages = sum(1 for text in page_texts if not text)
        if empty_pages:
            print(
                f"   Note: {empty_pages} page(s) had no text — they may be "
                "scanned pictures of pages."
            )
    else:
        print("   ⚠️  No text could be found in this PDF. It is probably a scanned")
        print("      document (photos of pages). To get the words out you'll need")
        print("      OCR (text recognition) software. Any pictures were still saved.")

    image_line = f"   Images saved: {images.saved}"
    if images.duplicates:
        image_line += f" ({images.duplicates} duplicate(s) skipped)"
    print(image_line)
    if images.unreadable:
        print(f"   {images.unreadable} picture(s) could not be read and were skipped.")

    print(f"   Done! Saved in: {OUTPUT_FOLDER_NAME}/{pdf_folder.name}/")
    print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python pdf_extractor.py
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
    print("  Tool: PDF Text & Image Extractor")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    pdfs = find_pdfs(input_dir)

    if not pdfs:
        print("No PDF files found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your .pdf files into it.")
        print("  3. Run this script again:")
        print()
        print("         python pdf_extractor.py")
        print()
        return

    total = len(pdfs)
    print(f"Found {total} PDF(s) to process. Starting now...")
    print()

    # Track folder names already used this run so two similar names
    # don't overwrite each other's results.
    used_names: set[str] = set()

    for i, pdf_path in enumerate(pdfs, start=1):
        process_one_pdf(pdf_path, output_dir, i, total, used_names)

    print("=" * 60)
    print(f"All done! Check the '{OUTPUT_FOLDER_NAME}' folder for your text and images.")
    print(f"Originals in '{INPUT_FOLDER_NAME}' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

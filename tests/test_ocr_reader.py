"""Tests for ocr_reader.py."""

import contextlib
import hashlib
import io
import logging
from types import SimpleNamespace

import numpy as np
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

import ocr_reader
from conftest import run_script

# Pillow's built-in font works the same on Windows, macOS and Linux.
# (It has no accented letters, so the sample text is plain English.)
FONT = ImageFont.load_default(size=36)
LINE_STEP = 60  # Pixels from one line of sample text to the next


# ---------------------------------------------------------------------------
# Making sample files
# ---------------------------------------------------------------------------

def text_picture(lines, size=(1000, 700), background="white", ink="black", mode="RGB"):
    """
    A clean "scan" with one line of text per item. An empty string leaves an
    empty line (a paragraph gap). A (left, right) pair puts the second part
    far to the right on the same line, like a price on a receipt.
    """
    picture = Image.new(mode, size, background)
    draw = ImageDraw.Draw(picture)
    y = 50
    for line in lines:
        if isinstance(line, tuple):
            draw.text((60, y), line[0], fill=ink, font=FONT)
            draw.text((size[0] - 260, y), line[1], fill=ink, font=FONT)
        elif line:
            draw.text((60, y), line, fill=ink, font=FONT)
        y += LINE_STEP
    return picture


def png_bytes(picture):
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return buffer.getvalue()


def make_pdf(path, pages, password=None, owner_password=None):
    """
    Build a small PDF where each page is either:
        {"scan": [lines]}  — a picture of text only (no real text inside)
        {"text": "..."}    — real typed text
    """
    pdf = FPDF(format=(150, 105))  # A small page keeps the tests quick
    pdf.set_font("Helvetica", size=12)
    for page in pages:
        pdf.add_page()
        if "scan" in page:
            pdf.image(io.BytesIO(png_bytes(text_picture(page["scan"]))), x=0, y=0, w=150)
        if "text" in page:
            pdf.multi_cell(w=0, h=8, text=page["text"])
    if password or owner_password:
        # RC4 protection works without any extra libraries
        pdf.set_encryption(owner_password=owner_password or "owner", user_password=password)
    path.write_bytes(bytes(pdf.output()))
    return path


def setup_input(workspace):
    folder = workspace / "input_scans"
    folder.mkdir()
    return folder


def read_result(workspace, name):
    return (workspace / "scanned_text" / name).read_text(encoding="utf-8")


def text_lines(text):
    """The non-empty lines of a result file, lowercased, without the header."""
    body = text.split("against the original.", 1)[-1]
    return [line.strip().lower() for line in body.splitlines() if line.strip()]


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# One real OCR engine shared by all tests (loading it takes a moment)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_engine():
    with contextlib.redirect_stdout(io.StringIO()):
        return ocr_reader.load_ocr_engine()


@pytest.fixture
def ocr(real_engine, monkeypatch):
    """Use the shared engine, and count how often the tool asks to load one."""
    counter = SimpleNamespace(loads=0)

    def shared_engine():
        counter.loads += 1
        return real_engine

    monkeypatch.setattr(ocr_reader, "load_ocr_engine", shared_engine)
    return counter


class FakeEngine:
    """Stands in for the OCR: returns the same made-up pieces for any picture."""

    def __init__(self, pieces):
        # pieces: list of (text, confidence, left, top, right, bottom)
        self.pieces = pieces

    def __call__(self, picture):
        if not self.pieces:
            return SimpleNamespace(boxes=None, txts=None, scores=None)
        boxes = np.array(
            [[[l, t], [r, t], [r, b], [l, b]] for _, _, l, t, r, b in self.pieces],
            dtype=np.float32,
        )
        texts = tuple(p[0] for p in self.pieces)
        scores = tuple(p[1] for p in self.pieces)
        return SimpleNamespace(boxes=boxes, txts=texts, scores=scores)


def fake_piece(text, left, middle, width=100, height=30, tilt=0.0, confidence=0.99):
    """A TextPiece for testing the line-building logic without any OCR."""
    return ocr_reader.TextPiece(text, confidence, left, left + width, middle, height, tilt)


# ---------------------------------------------------------------------------
# Rebuilding reading order (no OCR needed — fake pieces of text)
# ---------------------------------------------------------------------------

def test_pieces_are_put_in_reading_order():
    pieces = [
        fake_piece("world", 140, 101),
        fake_piece("again", 140, 141),
        fake_piece("Hello", 20, 99),
        fake_piece("Hello", 20, 138),
    ]

    lines = ocr_reader.arrange_into_lines(pieces)

    assert [[p.text for p in line] for line in lines] == [["Hello", "world"], ["Hello", "again"]]
    assert ocr_reader.lines_to_text(lines) == "Hello world\nHello again"


def test_tilted_page_keeps_each_line_together():
    # The page slopes down 8 px for every 100 px across, so the end of the
    # first line sits LOWER than the start of the second. Sorting by height
    # alone would mix the lines up.
    tilt = 0.08
    words = [["Alpha", "Bravo", "Charlie", "Delta"], ["Echo", "Foxtrot", "Golf", "Hotel"]]
    pieces = []
    for row, line in enumerate(words):
        for column, word in enumerate(line):
            left = 50 + column * 250
            centre_x = left + 100
            pieces.append(fake_piece(word, left, 100 + row * 45 + tilt * centre_x, width=200, tilt=tilt))
    assert pieces[3].middle > pieces[4].middle  # "Delta" is lower than "Echo"

    text = ocr_reader.lines_to_text(ocr_reader.arrange_into_lines(list(reversed(pieces))))

    assert text == "Alpha Bravo Charlie Delta\nEcho Foxtrot Golf Hotel"


def test_big_vertical_gap_starts_a_new_paragraph():
    pieces = [
        fake_piece("Dear", 20, 100),
        fake_piece("Sam,", 20, 140),  # Normal line spacing
        fake_piece("Thanks", 20, 260),  # A big empty gap above
    ]

    text = ocr_reader.lines_to_text(ocr_reader.arrange_into_lines(pieces))

    assert text == "Dear\nSam,\n\nThanks"


def test_wide_sideways_gap_keeps_columns_apart():
    pieces = [
        fake_piece("Coffee", 20, 100, width=120),
        fake_piece("3.50", 600, 100, width=60),
        fake_piece("Total", 20, 140, width=100),
        fake_piece("due", 130, 140, width=60),
    ]

    text = ocr_reader.lines_to_text(ocr_reader.arrange_into_lines(pieces))

    assert text == "Coffee    3.50\nTotal due"


def test_corner_points_become_a_text_piece():
    # A box sloping down 10 px over 200 px, 30 px tall
    box = [[100, 50], [300, 60], [300, 90], [100, 80]]

    piece = ocr_reader.make_piece(box, " Hello ", 0.93)

    assert piece.text == "Hello"
    assert (piece.left, piece.right, piece.middle) == (100, 300, 70)
    assert piece.height == pytest.approx(30)
    assert piece.tilt == pytest.approx(0.05)


def test_unclear_fragments_are_left_out_and_counted(monkeypatch):
    engine = FakeEngine([
        ("Invoice", 0.98, 20, 20, 200, 50),
        ("~~", 0.21, 300, 20, 340, 50),
        ("4821", 0.62, 220, 20, 290, 50),
    ])

    result = ocr_reader.read_picture(engine, Image.new("RGB", (10, 10)))
    assert result.text == "Invoice 4821"
    assert result.left_out == 1

    monkeypatch.setattr(ocr_reader, "MIN_CONFIDENCE", 0.7)
    stricter = ocr_reader.read_picture(engine, Image.new("RGB", (10, 10)))
    assert stricter.text == "Invoice"
    assert stricter.left_out == 2


def test_reading_quality_labels():
    assert ocr_reader.describe_quality(0.97) == "✓ clear (average confidence 97%)"
    assert ocr_reader.describe_quality(0.998) == "✓ clear (average confidence 99%)"
    assert "a few words may be wrong" in ocr_reader.describe_quality(0.8)
    assert "some words may be wrong — check the original" in ocr_reader.describe_quality(0.6)
    assert "no OCR needed" in ocr_reader.describe_quality(None)


# ---------------------------------------------------------------------------
# Real OCR on generated pictures and PDFs
# ---------------------------------------------------------------------------

def test_photo_text_is_read_in_reading_order(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    picture = text_picture([
        ("Invoice number 4821", "Paid"),
        "Customer Alice Smith",
        "Total due 120 dollars",
        "",
        "",
        "Thank you for your business",
    ])
    picture.save(inputs / "invoice.png")

    ocr_reader.main()

    text = read_result(workspace, "invoice.txt")
    assert text.startswith("Text read from: invoice.png\nPages: 1\n")
    assert "Page 1 of" not in text  # Single pictures don't need page headers
    assert text_lines(text) == [
        "invoice number 4821    paid",
        "customer alice smith",
        "total due 120 dollars",
        "thank you for your business",
    ]
    assert "dollars\n\nThank you" in text  # The big gap became a paragraph break
    out = capsys.readouterr().out
    assert "Reading file 1 of 1: invoice.png ..." in out
    assert "Words found: 16" in out
    assert "Reading quality: ✓ clear" in out
    assert "Done! Saved as: invoice.txt" in out
    assert ocr.loads == 1


def test_scanned_pdf_pages_get_headers_and_progress(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "contract.pdf", [
        {"scan": ["Rental agreement"]},
        {"scan": ["The rent is due monthly"]},
        {"scan": ["Signed by both parties"]},
    ])

    ocr_reader.main()

    text = read_result(workspace, "contract.txt")
    assert text.index("----- Page 1 of 3 -----") < text.index("Rental agreement")
    assert text.index("----- Page 2 of 3 -----") < text.index("The rent is due monthly")
    assert text.index("----- Page 3 of 3 -----") < text.index("Signed by both parties")
    out = capsys.readouterr().out
    assert "   Reading page 1 of 3...\n   Reading page 2 of 3...\n   Reading page 3 of 3...\n" in out
    assert "Pages: 3" in out
    assert "Words found: 11" in out


def test_pdf_with_real_text_uses_it_directly(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    typed = "Minutes of the board meeting held on 3 May"
    make_pdf(inputs / "mixed.pdf", [{"text": typed}, {"scan": ["Handwritten notes page"]}])
    make_pdf(inputs / "typed.pdf", [{"text": "A typed letter with real text inside it"}])

    ocr_reader.main()

    mixed = read_result(workspace, "mixed.txt")
    assert f"----- Page 1 of 2 -----\n\n{typed}\n" in mixed
    assert "Handwritten notes page" in mixed
    typed_result = read_result(workspace, "typed.txt")
    assert typed_result.endswith("\n\nA typed letter with real text inside it\n")
    assert "Read by OCR" not in typed_result  # Nothing in it came from OCR
    out = capsys.readouterr().out
    assert "Reading page 1 of 2... (already has real text — copied it exactly)" in out
    assert "1 of 2 page(s) already had real text" in out
    assert "1 of 1 page(s) already had real text" in out
    assert "Reading quality: ✓ exact (copied from the PDF's own text" in out


def test_page_with_only_a_little_text_is_still_read_with_ocr(workspace, ocr):
    inputs = setup_input(workspace)
    # A scanned page with a tiny typed footer: the footer alone isn't enough
    pdf = FPDF(format=(150, 105))
    pdf.add_page()
    pdf.image(io.BytesIO(png_bytes(text_picture(["Scanned body text"]))), x=0, y=0, w=150)
    pdf.set_font("Helvetica", size=8)
    pdf.set_xy(10, 95)
    pdf.cell(text="Page 1")
    pdf.output(str(inputs / "footer.pdf"))

    ocr_reader.main()

    assert "Scanned body text" in read_result(workspace, "footer.txt")


def test_rotated_phone_photo_is_turned_upright(workspace, ocr):
    inputs = setup_input(workspace)
    upright = text_picture(["Meeting notes", "Buy more coffee"], size=(800, 300))
    # Phones often save the picture sideways plus a note saying "rotate me"
    sideways = upright.rotate(90, expand=True)
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to view
    sideways.save(inputs / "phone_photo.jpg", exif=exif, quality=95)

    ocr_reader.main()

    assert text_lines(read_result(workspace, "phone_photo.txt")) == [
        "meeting notes",
        "buy more coffee",
    ]


def test_see_through_screenshot_is_read(workspace, ocr):
    inputs = setup_input(workspace)
    # Black text on a transparent background (would be black-on-black if
    # the transparency were simply dropped)
    text_picture(["Error code 404"], size=(600, 200), background=(0, 0, 0, 0),
                 ink=(0, 0, 0, 255), mode="RGBA").save(inputs / "screenshot.png")

    ocr_reader.main()

    assert "Error code 404" in read_result(workspace, "screenshot.txt")


def test_16_bit_scan_is_read(workspace, ocr):
    inputs = setup_input(workspace)
    grey = np.asarray(text_picture(["Deep scan text"], size=(600, 200)).convert("L"), dtype=np.uint16)
    Image.fromarray(grey * 257).save(inputs / "scanner.tif")  # 0-255 → 0-65535

    ocr_reader.main()

    assert "Deep scan text" in read_result(workspace, "scanner.txt")


def test_multi_page_tiff_gets_page_headers(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    first = text_picture(["First fax page"], size=(600, 200))
    second = text_picture(["Second fax page"], size=(600, 200))
    first.save(inputs / "fax.tif", save_all=True, append_images=[second])

    ocr_reader.main()

    text = read_result(workspace, "fax.txt")
    assert text.index("----- Page 1 of 2 -----") < text.index("First fax page")
    assert text.index("----- Page 2 of 2 -----") < text.index("Second fax page")
    assert "Reading page 2 of 2..." in capsys.readouterr().out


def test_blank_picture_says_no_text_found(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    Image.new("RGB", (800, 600), (250, 250, 250)).save(inputs / "blank.png")

    ocr_reader.main()

    out = capsys.readouterr().out
    assert "⚠️  No text found" in out
    assert "Nothing was saved for this file." in out
    assert list((workspace / "scanned_text").iterdir()) == []
    assert "All done!" in out


def test_blank_page_inside_a_pdf_is_marked(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "gap.pdf", [{"scan": ["Before the blank"]}, {"scan": []}])

    ocr_reader.main()

    text = read_result(workspace, "gap.txt")
    assert "----- Page 2 of 2 -----\n\n[No text found on this page]" in text
    assert "1 page(s) had no readable text" in capsys.readouterr().out


def test_broken_files_are_skipped_and_others_still_work(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_fake.jpg").write_bytes(b"this is really a text file")
    (inputs / "b_empty.png").write_bytes(b"")
    (inputs / "c_broken.pdf").write_bytes(b"%PDF-1.4 not really")
    text_picture(["Still works"], size=(500, 200)).save(inputs / "d_good.png")

    ocr_reader.main()

    out = capsys.readouterr().out
    assert out.count("Skipped this file — this file could not be opened as a picture") == 2
    assert out.count("Skipped this file — this file could not be opened as a PDF") == 1
    assert sorted(p.name for p in (workspace / "scanned_text").iterdir()) == ["d_good.txt"]
    assert "Still works" in read_result(workspace, "d_good.txt")
    assert "All done!" in out


def test_password_protected_pdf_is_skipped_but_blank_password_opens(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "a_secret.pdf", [{"scan": ["Top secret"]}], password="letmein")
    make_pdf(inputs / "b_locked.pdf", [{"scan": ["Print locked only"]}], owner_password="boss")

    ocr_reader.main()

    out = capsys.readouterr().out
    assert "Skipped this file — this PDF is password-protected" in out
    assert not (workspace / "scanned_text" / "a_secret.txt").exists()
    assert "Print locked only" in read_result(workspace, "b_locked.txt")


def test_huge_picture_is_shrunk_before_reading():
    big = Image.new("RGB", (6000, 4000), "white")  # 24 megapixels

    prepared = ocr_reader.prepare_picture(big)

    width, height = prepared.size
    assert width * height <= ocr_reader.MAX_PICTURE_MEGAPIXELS * 1_000_000
    assert abs(width / height - 1.5) < 0.01  # Same shape, just smaller


def test_enormous_picture_is_skipped_with_advice(workspace, ocr, capsys, monkeypatch):
    inputs = setup_input(workspace)
    Image.new("RGB", (400, 400), "white").save(inputs / "poster.png")
    # Pretend this is a gigantic picture by lowering Pillow's safety limit
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)

    ocr_reader.main()

    assert "Skipped this file — this picture is far too big to open safely" in capsys.readouterr().out


def test_same_name_clash_and_originals_untouched(workspace, ocr):
    inputs = setup_input(workspace)
    text_picture(["Receipt photo"], size=(500, 200)).save(inputs / "receipt.png")
    make_pdf(inputs / "receipt.pdf", [{"scan": ["Receipt scan"]}])
    make_pdf(inputs / "locked.pdf", [{"scan": ["Locked"]}], owner_password="boss")
    (inputs / "broken.jpg").write_bytes(b"broken")
    before = {p.name: file_hash(p) for p in inputs.iterdir()}

    ocr_reader.main()

    after = {p.name: file_hash(p) for p in inputs.iterdir()}
    assert after == before
    outputs = sorted(p.name for p in (workspace / "scanned_text").iterdir())
    assert outputs == ["locked.txt", "receipt.txt", "receipt_png.txt"]
    assert "Receipt scan" in read_result(workspace, "receipt.txt")
    assert "Receipt photo" in read_result(workspace, "receipt_png.txt")


def test_hidden_and_unsupported_files_are_explained(workspace, ocr, capsys):
    inputs = setup_input(workspace)
    text_picture(["Real file"], size=(500, 200)).save(inputs / "real.png")
    (inputs / "._real.png").write_bytes(b"macOS leftover")
    (inputs / "IMG_0042.HEIC").write_bytes(b"iphone photo")
    (inputs / "notes.docx").write_bytes(b"word file")
    (inputs / "old").mkdir()

    ocr_reader.main()

    out = capsys.readouterr().out
    assert "Note: ignored 2 file(s) this tool can't read: IMG_0042.HEIC, notes.docx" in out
    assert "export/share as JPEG" in out
    assert "Found 1 file(s) to read." in out


@pytest.mark.parametrize("already_there", [False, True])
def test_creates_folders_and_explains_next_steps(workspace, ocr, capsys, already_there):
    if already_there:
        setup_input(workspace)

    ocr_reader.main()

    assert (workspace / "input_scans").is_dir()
    assert (workspace / "scanned_text").is_dir()
    out = capsys.readouterr().out
    assert ("📁 Created folder:" in out) is not already_there
    assert "No scans, photos or screenshots found yet." in out
    assert "python ocr_reader.py" in out
    # Nothing to do means no reason to load (or download) the model
    assert ocr.loads == 0


# ---------------------------------------------------------------------------
# Loading the model (first-run download messages)
# ---------------------------------------------------------------------------

def fake_rapidocr(download_works):
    """A stand-in for rapidocr that pretends its model has to be downloaded."""

    class FakeRapidOCR:
        def __init__(self, params=None):
            logging.getLogger("RapidOCR").info("Initiating download: https://example.com/model.onnx")
            if not download_works:
                raise ConnectionError("Failed to download https://example.com/model.onnx")

        def __call__(self, picture):
            return FakeEngine([("Downloaded fine", 0.95, 20, 20, 300, 50)])(picture)

    return FakeRapidOCR


def test_first_run_download_is_explained(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    Image.new("RGB", (300, 100), "white").save(inputs / "note.png")
    monkeypatch.setattr(ocr_reader, "RapidOCR", fake_rapidocr(download_works=True))

    ocr_reader.main()

    out = capsys.readouterr().out
    assert "First run: downloading the text recognition model (about 32 MB)." in out
    assert "your\n   documents are NOT uploaded" in out
    assert "Ready! Model downloaded and saved for next time." in out
    assert "Downloaded fine" in read_result(workspace, "note.txt")


def test_model_download_failure_explains_what_to_do(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    Image.new("RGB", (300, 100), "white").save(inputs / "note.png")
    monkeypatch.setattr(ocr_reader, "RapidOCR", fake_rapidocr(download_works=False))

    with pytest.raises(SystemExit) as stopped:
        ocr_reader.main()

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "The text recognition model could not be downloaded." in out
    assert "modelscope.cn" in out
    assert "Check your internet connection" in out
    assert list((workspace / "scanned_text").iterdir()) == []


# ---------------------------------------------------------------------------
# Running it exactly like a user would
# ---------------------------------------------------------------------------

def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    text_picture(["Parking permit", "Valid until June"], size=(700, 250)).save(inputs / "permit.jpg")
    make_pdf(inputs / "letter.pdf", [{"scan": ["Dear neighbour"]}, {"scan": ["Kind regards"]}])

    result = run_script("ocr_reader.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Ready! (found on this computer — no internet needed)" in result.stdout
    assert "Reading page 2 of 2..." in result.stdout
    assert "All done!" in result.stdout
    assert text_lines(read_result(workspace, "permit.txt")) == ["parking permit", "valid until june"]
    letter = read_result(workspace, "letter.txt")
    assert "Dear neighbour" in letter
    assert "Kind regards" in letter

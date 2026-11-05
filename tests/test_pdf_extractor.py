"""Tests for pdf_extractor.py."""

import hashlib
import io

import pytest
from fpdf import FPDF
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError

import pdf_extractor
from conftest import run_script


def setup_input(workspace):
    folder = workspace / "input_pdfs"
    folder.mkdir()
    return folder


def picture_bytes(color, size=(24, 16), image_format="PNG"):
    """A small solid-color picture, made in memory."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, image_format)
    return buffer.getvalue()


def make_pdf(path, pages, password=None, owner_password=None):
    """
    Build a PDF where each page is a dict like:
        {"text": "Hello", "images": [png_bytes, ...]}
    """
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for page in pages:
        pdf.add_page()
        if page.get("text"):
            pdf.multi_cell(w=0, h=8, text=page["text"])
        for i, data in enumerate(page.get("images", [])):
            pdf.image(io.BytesIO(data), x=10 + i * 40, y=120, w=30)
    if password or owner_password:
        # RC4 protection works without any extra libraries
        pdf.set_encryption(owner_password=owner_password or "owner", user_password=password)
    path.write_bytes(bytes(pdf.output()))
    return path


def results_folder(workspace, name):
    return workspace / "extracted_pdfs" / name


def read_text_file(workspace, name):
    return (results_folder(workspace, name) / f"{name}.txt").read_text(encoding="utf-8")


def test_text_from_every_page_with_page_headers(workspace, capsys):
    inputs = setup_input(workspace)
    make_pdf(
        inputs / "report.pdf",
        [
            {"text": "Quarterly report"},
            {"text": "Sales went up at the Cafe"},
            {"text": "Final page here"},
        ],
    )

    pdf_extractor.main()

    text = read_text_file(workspace, "report")
    assert text.index("----- Page 1 of 3 -----") < text.index("Quarterly report")
    assert text.index("----- Page 2 of 3 -----") < text.index("Sales went up")
    assert text.index("----- Page 3 of 3 -----") < text.index("Final page here")
    out = capsys.readouterr().out
    assert "Extracting PDF 1 of 1: report.pdf ..." in out
    assert "Pages: 3" in out
    assert "Text: 11 words" in out
    assert "Images saved: 0" in out


def test_accented_text_is_saved_as_utf8(workspace):
    inputs = setup_input(workspace)
    make_pdf(inputs / "menu.pdf", [{"text": "Café crème £3"}])

    pdf_extractor.main()

    assert "Café crème £3" in read_text_file(workspace, "menu")


def test_page_text_is_tidied_for_notepad():
    raw = "Title   \r\n\r\nPara one\x00 \n\n\n\n\n\nPara two\t \n\n\nPara three\n\n"

    cleaned = pdf_extractor.clean_page_text(raw)

    # 5 empty lines become 1; 2 empty lines are left alone
    assert cleaned == "Title\n\nPara one\n\nPara two\n\n\nPara three"


def test_images_saved_with_clear_names_and_duplicates_skipped(workspace, capsys):
    inputs = setup_input(workspace)
    logo = picture_bytes((200, 30, 30), size=(24, 16))
    photo = picture_bytes((30, 30, 200), size=(40, 30), image_format="JPEG")
    make_pdf(
        inputs / "brochure.pdf",
        [
            {"text": "Page one", "images": [logo]},
            {"text": "Page two", "images": [logo, photo]},
            {"text": "Page three", "images": [logo]},
        ],
    )

    pdf_extractor.main()

    images_dir = results_folder(workspace, "brochure") / "images"
    assert sorted(p.name for p in images_dir.iterdir()) == [
        "page01_image01.png",
        "page02_image02.jpg",
    ]
    with Image.open(images_dir / "page01_image01.png") as saved_logo:
        assert saved_logo.size == (24, 16)
    with Image.open(images_dir / "page02_image02.jpg") as saved_photo:
        assert saved_photo.size == (40, 30)
    assert "Images saved: 2 (2 duplicate(s) skipped)" in capsys.readouterr().out


def test_pdf_without_images_has_no_images_folder(workspace):
    inputs = setup_input(workspace)
    make_pdf(inputs / "letter.pdf", [{"text": "Dear reader"}])

    pdf_extractor.main()

    folder = results_folder(workspace, "letter")
    assert sorted(p.name for p in folder.iterdir()) == ["letter.txt"]


def test_image_only_pdf_explains_ocr_and_still_saves_images(workspace, capsys):
    inputs = setup_input(workspace)
    make_pdf(
        inputs / "scan.pdf",
        [
            {"images": [picture_bytes((10, 10, 10))]},
            {"images": [picture_bytes((90, 90, 90))]},
        ],
    )

    pdf_extractor.main()

    out = capsys.readouterr().out
    assert "No text could be found in this PDF" in out
    assert "OCR" in out
    assert "Images saved: 2" in out
    text = read_text_file(workspace, "scan")
    assert "OCR" in text
    assert "----- Page 2 of 2 -----" in text
    assert len(list((results_folder(workspace, "scan") / "images").iterdir())) == 2


def test_password_protected_pdf_is_skipped_and_others_still_work(workspace, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "a_secret.pdf", [{"text": "Top secret"}], password="letmein")
    make_pdf(inputs / "b_open.pdf", [{"text": "Hello there"}])

    pdf_extractor.main()

    out = capsys.readouterr().out
    assert "Skipped this file — this PDF is password-protected" in out
    assert not results_folder(workspace, "a_secret").exists()
    assert "Hello there" in read_text_file(workspace, "b_open")
    assert "All done!" in out


def test_pdf_locked_with_blank_password_still_opens(workspace, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "locked.pdf", [{"text": "Read me anyway"}], owner_password="boss")

    pdf_extractor.main()

    assert "Read me anyway" in read_text_file(workspace, "locked")
    assert "blank password" in capsys.readouterr().out


def test_strong_protection_explains_extra_install(workspace, capsys, monkeypatch):
    inputs = setup_input(workspace)
    make_pdf(inputs / "aes.pdf", [{"text": "Hidden"}], owner_password="boss")

    def needs_extra_library(self, password):
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(PdfReader, "decrypt", needs_extra_library)

    pdf_extractor.main()

    assert "pip install cryptography" in capsys.readouterr().out
    assert not results_folder(workspace, "aes").exists()


def test_broken_files_are_skipped_and_others_still_work(workspace, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_fake.pdf").write_bytes(b"this is really a text file")
    (inputs / "b_empty.pdf").write_bytes(b"")
    make_pdf(inputs / "c_good.pdf", [{"text": "Still works"}])

    pdf_extractor.main()

    out = capsys.readouterr().out
    assert out.count("could not be opened as a PDF") == 2
    assert not results_folder(workspace, "a_fake").exists()
    assert "Still works" in read_text_file(workspace, "c_good")


def test_unreadable_image_is_skipped_and_others_kept(workspace, capsys):
    inputs = setup_input(workspace)
    pdf = FPDF()
    pdf.add_page()
    pdf.image(io.BytesIO(picture_bytes((255, 0, 0))), x=10, y=10, w=20)
    pdf.image(io.BytesIO(picture_bytes((0, 255, 0))), x=40, y=10, w=20)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(bytes(pdf.output()))))
    first_image = writer.pages[0]["/Resources"]["/XObject"]["/I1"].get_object()
    first_image._data = b"scrambled picture data"  # Not valid compressed data
    with open(inputs / "damaged.pdf", "wb") as handle:
        writer.write(handle)

    pdf_extractor.main()

    out = capsys.readouterr().out
    assert "Could not read picture 1 on page 1" in out
    assert "Images saved: 1" in out
    images_dir = results_folder(workspace, "damaged") / "images"
    assert [p.name for p in images_dir.iterdir()] == ["page01_image02.png"]


def test_rerun_replaces_old_pictures(workspace):
    inputs = setup_input(workspace)
    source = inputs / "flyer.pdf"
    make_pdf(source, [{"text": "v1", "images": [picture_bytes((1, 2, 3))]}] * 2 + [
        {"text": "v1", "images": [picture_bytes((4, 5, 6))]}
    ])
    pdf_extractor.main()
    images_dir = results_folder(workspace, "flyer") / "images"
    assert len(list(images_dir.iterdir())) == 2

    make_pdf(source, [{"text": "Version two only text"}])
    pdf_extractor.main()

    assert not images_dir.exists()
    assert "Version two only text" in read_text_file(workspace, "flyer")


def test_originals_untouched(workspace):
    inputs = setup_input(workspace)
    make_pdf(inputs / "one.pdf", [{"text": "One", "images": [picture_bytes((5, 5, 5))]}])
    make_pdf(inputs / "two.pdf", [{"text": "Two"}], owner_password="boss")
    (inputs / "three.pdf").write_bytes(b"broken")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}

    pdf_extractor.main()

    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    assert after == before
    assert sorted(p.name for p in (workspace / "extracted_pdfs").iterdir()) == ["one", "two"]


def test_hidden_and_non_pdf_files_are_ignored(workspace, capsys):
    inputs = setup_input(workspace)
    make_pdf(inputs / "real.pdf", [{"text": "Real"}])
    (inputs / "._real.pdf").write_bytes(b"macOS leftover")
    (inputs / "notes.txt").write_text("not a pdf")

    pdf_extractor.main()

    assert "Found 1 PDF(s)" in capsys.readouterr().out


@pytest.mark.parametrize("already_there", [False, True])
def test_creates_folders_and_explains_next_steps(workspace, capsys, already_there):
    if already_there:
        setup_input(workspace)

    pdf_extractor.main()

    assert (workspace / "input_pdfs").is_dir()
    assert (workspace / "extracted_pdfs").is_dir()
    out = capsys.readouterr().out
    assert ("📁 Created folder:" in out) is not already_there
    assert "No PDF files found yet." in out


def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    make_pdf(
        inputs / "terminal.pdf",
        [{"text": "From the terminal", "images": [picture_bytes((7, 7, 7))]}],
    )

    result = run_script("pdf_extractor.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "All done!" in result.stdout
    assert "From the terminal" in read_text_file(workspace, "terminal")
    assert (results_folder(workspace, "terminal") / "images" / "page01_image01.png").exists()

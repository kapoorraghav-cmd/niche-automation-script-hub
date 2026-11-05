"""Tests for mail_merge.py."""

import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest
from docx import Document
from docx.oxml import parse_xml
from lxml import etree

import mail_merge
from conftest import PROJECT_ROOT, run_script

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A text box (Word's older "VML" kind), with its placeholder split over two runs
TEXT_BOX_XML = (
    '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml"><w:pict>'
    '<v:shape style="width:200pt;height:40pt"><v:textbox><w:txbxContent>'
    '<w:p><w:r><w:t>Box: {{Last</w:t></w:r><w:r><w:t xml:space="preserve"> Name}}</w:t></w:r></w:p>'
    "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
)


@pytest.fixture(autouse=True)
def word_files_only(monkeypatch):
    """Most tests don't need PDFs (and test computers may not have LibreOffice)."""
    monkeypatch.setattr(mail_merge, "MAKE_PDFS", False)


def setup_input(workspace):
    folder = workspace / "mail_merge"
    folder.mkdir()
    return folder


def write_csv(path, text, encoding="utf-8"):
    path.write_text(text, encoding=encoding)
    return path


def simple_template(path, *lines):
    """A Word file with one paragraph per line of text."""
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(path)
    return path


def answer_with(monkeypatch, *answers):
    """Pretend the user types these answers, in order, at each question."""
    replies = iter(answers)

    def fake_input(prompt=""):
        print(prompt)
        try:
            return next(replies)
        except StopIteration:
            raise AssertionError(f"Unexpected question: {prompt}") from None

    monkeypatch.setattr("builtins.input", fake_input)


def output_names(workspace):
    return sorted(p.name for p in (workspace / "merged_documents").iterdir())


def document_lines(path):
    """Every paragraph's text in a Word file: main text, tables, text boxes, headers, footers."""
    lines = []
    with zipfile.ZipFile(path) as package:
        for name in sorted(package.namelist()):
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", name):
                root = etree.fromstring(package.read(name))
                for paragraph in root.iter(W + "p"):
                    lines.append("".join(t.text or "" for t in paragraph.iter(W + "t")))
    return lines


def fingerprints(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}


def run_in_terminal(cwd, typed_text):
    """Run the tool like a user would, typing the given text into the terminal."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "mail_merge.py")],
        cwd=cwd,
        input=typed_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_placeholders_are_filled_everywhere_even_when_word_splits_them(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    document = Document()
    section = document.sections[0]
    section.header.paragraphs[0].text = "Ref {{ ID }}"
    section.footer.paragraphs[0].text = "Issued to {{first   NAME}}"

    # Word stored this placeholder in four pieces with different formatting
    letter = document.add_paragraph("Dear ")
    letter.add_run("{{").bold = True
    letter.add_run("First ")
    letter.add_run("Na").italic = True
    letter.add_run("me}}, welcome!")

    # ... and this one with the braces themselves split up
    course = document.add_paragraph()
    for piece in ("{", "{Course}", "}"):
        course.add_run(piece)

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "{{  COURSE  }}"
    table.cell(0, 1).text = "{{start date}}"

    document.add_paragraph()._p.append(parse_xml(TEXT_BOX_XML))
    document.save(inputs / "letter.docx")

    write_csv(
        inputs / "people.csv",
        "First Name,Last Name,Course,Start  Date,ID\nAda,Lovelace,Maths,1 May 2026,007\n",
    )

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert 'column "ID"  (in the header)' in out
    assert 'column "First Name"  (also in the footer)' in out
    assert output_names(workspace) == ["Ada Lovelace.docx"]

    result = workspace / "merged_documents" / "Ada Lovelace.docx"
    lines = document_lines(result)
    assert "Dear Ada, welcome!" in lines
    assert "Maths" in lines
    assert "1 May 2026" in lines
    assert "Ref 007" in lines
    assert "Issued to Ada" in lines
    assert "Box: Lovelace" in lines
    assert not any("{" in line or "}" in line for line in lines)

    # The filled-in name keeps the formatting of the placeholder's first piece
    merged = Document(result)
    name_run = next(r for r in merged.paragraphs[0].runs if "Ada" in r.text)
    assert name_run.bold


def test_matching_ignores_capitals_spaces_and_curly_quotes(workspace, monkeypatch):
    inputs = setup_input(workspace)
    # \u00a0 is Word's "non-breaking space"; ’ is Word's curly apostrophe
    simple_template(inputs / "t.docx", "{{MANAGER’S\u00a0name}} / {{ first name }}")
    write_csv(inputs / "d.csv", "First Name,Last Name,Manager's Name\nAda,Lovelace,Charles Babbage\n")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    lines = document_lines(workspace / "merged_documents" / "Ada Lovelace.docx")
    assert "Charles Babbage / Ada" in lines


def test_excel_values_dates_numbers_and_leading_zeros(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(
        inputs / "card.docx",
        "{{Member ID}}|{{Joined}}|{{Last Visit}}|{{Visits}}|{{Score}}|{{Fee}}|{{Paid}}|{{Status}}|end",
        "{{Notes}}",
    )
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Members"
    sheet.append(["First Name", "Last Name", "Member ID", "Joined", "Last Visit", "Visits",
                  "Score", "Fee", "Paid", "Status", "Notes"])
    sheet.append(["Grace", "Hopper", "00123", datetime(2026, 3, 5), datetime(2026, 4, 1, 14, 30),
                  12, 7.0, 2.5, None, "N/A", "Line one\nLine two"])
    book.create_sheet("Old list").append(["Ignored"])
    book.save(inputs / "members.xlsx")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "Using the first sheet, 'Members' (this workbook has 2 sheets)." in out
    result = workspace / "merged_documents" / "Grace Hopper.docx"
    lines = document_lines(result)
    assert "00123|05 March 2026|01 April 2026 14:30|12|7|2.5||N/A|end" in lines
    # A line break typed inside the cell (Alt+Enter) stays a line break
    assert Document(result).paragraphs[1].text == "Line one\nLine two"


def test_csv_text_is_kept_exactly_as_typed(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "{{Name}} {{Code}} {{Status}} {{Price}} {{Company}} {{Phone}}")
    write_csv(
        inputs / "d.csv",
        "Name,Code,Status,Price,Company,Phone\nZoë,007,N/A,£2.50,Smith & Co <Ltd>,020 7946 0958\n",
        encoding="cp1252",
    )

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    # The default FILE_NAME_PATTERN uses {{First Name}}, which this file doesn't have
    assert "uses {{First Name}}, which isn't a column" in out
    assert output_names(workspace) == ["Document_001.docx"]
    lines = document_lines(workspace / "merged_documents" / "Document_001.docx")
    assert "Zoë 007 N/A £2.50 Smith & Co <Ltd> 020 7946 0958" in lines


def test_unknown_placeholder_stops_with_a_suggestion(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Dear {{Frist Name}}, you won {{Award}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch)  # no questions should be asked
    mail_merge.main()

    out = capsys.readouterr().out
    assert "don't match any column heading" in out
    assert "{{Frist Name}}  (did you mean {{First Name}}?)" in out
    assert "{{Award}}  (no similar column found)" in out
    assert "First Name, Last Name" in out
    assert output_names(workspace) == []


def test_cancel_creates_nothing(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hello {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\nGrace,Hopper\n")

    answer_with(monkeypatch, "n")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "Create 2 documents? Type y to continue:" in out
    assert "Cancelled — nothing was created." in out
    assert output_names(workspace) == []


def test_file_names_are_safe_and_never_clash(workspace, monkeypatch):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "{{First Name}}")
    write_csv(
        inputs / "d.csv",
        "First Name,Last Name\n"
        "Ada,Lovelace\n"
        "ada,lovelace\n"
        "A/B: Test?,Smith*\n"
        "...,\n"
        "CON,\n"
        ". Hidden,Name .\n"
        "Ada,Lovelace\n",
    )

    answer_with(monkeypatch, "y")
    mail_merge.main()

    assert output_names(workspace) == sorted([
        "Ada Lovelace.docx",
        "ada lovelace_2.docx",
        "A_B_ Test_ Smith_.docx",
        "Document_004.docx",
        "CON_.docx",
        "Hidden Name.docx",
        "Ada Lovelace_3.docx",
    ])


def test_make_safe_file_name_rules():
    assert mail_merge.make_safe_file_name('  Q3: "Report"  ') == "Q3_ _Report_"
    assert mail_merge.make_safe_file_name("Line\nbreak\ttab") == "Line break tab"
    assert mail_merge.make_safe_file_name("...") == ""
    assert mail_merge.make_safe_file_name("nul") == "nul_"
    assert mail_merge.make_safe_file_name("Café Zoë") == "Café Zoë"
    assert len(mail_merge.make_safe_file_name("x" * 300)) == mail_merge.MAX_FILE_NAME_LENGTH


def test_empty_rows_are_skipped_and_a_failing_row_does_not_stop_the_rest(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hi {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n,\n\nGrace,Hopper\nAlan,Turing\n")
    # Something already in the way of Grace's document (like a file open in Word)
    (workspace / "merged_documents").mkdir()
    (workspace / "merged_documents" / "Grace Hopper.docx").mkdir()

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "(2 completely empty row(s) in the spreadsheet will be skipped.)" in out
    assert "Skipped row 5" in out
    assert "1 row(s) were skipped" in out
    assert (workspace / "merged_documents" / "Ada Lovelace.docx").is_file()
    assert (workspace / "merged_documents" / "Alan Turing.docx").is_file()


def test_example_files_are_created_on_first_run_and_work(workspace, monkeypatch, capsys):
    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "Created folder" in out
    assert "example files were added" in out
    assert sorted(p.name for p in (workspace / "mail_merge").iterdir()) == [
        "example_people.csv",
        "example_template.docx",
    ]
    assert output_names(workspace) == ["Mei Chen.docx", "Priya Sharma.docx", "Tom O'Neill.docx"]
    lines = document_lines(workspace / "merged_documents" / "Tom O'Neill.docx")
    assert "Tom O'Neill" in lines
    assert "First Aid at Work" in lines
    assert "Certificate No. 00042" in lines


def test_examples_are_not_added_when_the_user_has_files(workspace, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "mine.docx", "{{Name}}")
    (inputs / "~$mine.docx").write_bytes(b"Word lock file")
    (inputs / "old.doc").write_bytes(b"old Word file")

    mail_merge.main()

    out = capsys.readouterr().out
    assert "No spreadsheet (.xlsx, .xls or .csv) found yet." in out
    assert "'old.doc' can't be used as a template" in out
    assert sorted(p.name for p in inputs.iterdir()) == ["mine.docx", "old.doc", "~$mine.docx"]


def test_several_templates_asks_which_one(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "a_invite.docx", "Invite for {{First Name}}")
    simple_template(inputs / "b_award.docx", "Award for {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch, "5", "2", "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "1. a_invite.docx" in out
    assert "Please type a number from 1 to 2." in out
    assert "Award for Ada" in document_lines(workspace / "merged_documents" / "Ada Lovelace.docx")


def test_broken_placeholders_stop_with_an_explanation(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Dear {{First Name}, hello", "Empty {{ }} here")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch)  # no questions should be asked
    mail_merge.main()

    out = capsys.readouterr().out
    assert "missing a brace" in out
    assert "{{First Name}, hello" in out
    assert "empty {{}}" in out
    assert output_names(workspace) == []


def test_other_brace_text_is_kept_exactly(workspace, monkeypatch):
    inputs = setup_input(workspace)
    literal = "Use {% and %} and {# and #} and C# {single} braces"
    simple_template(inputs / "t.docx", literal, "{{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    lines = document_lines(workspace / "merged_documents" / "Ada Lovelace.docx")
    assert lines[:2] == [literal, "Ada"]


def test_originals_are_never_changed(workspace, monkeypatch):
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hello {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")
    before = fingerprints(inputs)

    answer_with(monkeypatch, "y")
    mail_merge.main()

    assert fingerprints(inputs) == before
    assert output_names(workspace) == ["Ada Lovelace.docx"]


def test_without_libreoffice_the_word_files_are_still_made(workspace, monkeypatch, capsys):
    monkeypatch.setattr(mail_merge, "MAKE_PDFS", True)
    monkeypatch.setattr(mail_merge, "find_libreoffice", lambda: None)
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hello {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "LibreOffice isn't installed" in out
    assert "https://www.libreoffice.org/download/" in out
    assert output_names(workspace) == ["Ada Lovelace.docx"]


def test_a_broken_libreoffice_is_explained(workspace, monkeypatch, capsys):
    monkeypatch.setattr(mail_merge, "MAKE_PDFS", True)
    # Python itself stands in for a LibreOffice that fails to start
    monkeypatch.setattr(mail_merge, "find_libreoffice", lambda: sys.executable)
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hello {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\n")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert "LibreOffice didn't create any PDFs" in out
    assert output_names(workspace) == ["Ada Lovelace.docx"]


def test_pdfs_are_made_in_batches_and_combined(workspace, monkeypatch, capsys):
    from pypdf import PdfReader, PdfWriter

    commands = []

    def stand_in_libreoffice(command, **options):
        """Behaves like 'soffice --convert-to pdf': one blank PDF per document."""
        commands.append(command)
        outdir = Path(command[command.index("--outdir") + 1])
        for document in command[command.index("--outdir") + 2:]:
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with open(outdir / f"{Path(document).stem}.pdf", "wb") as f:
                writer.write(f)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mail_merge, "MAKE_PDFS", True)
    monkeypatch.setattr(mail_merge, "COMBINE_INTO_ONE_PDF", True)
    monkeypatch.setattr(mail_merge, "PDF_BATCH_SIZE", 2)
    monkeypatch.setattr(mail_merge, "find_libreoffice", lambda: "soffice")
    monkeypatch.setattr(mail_merge.subprocess, "run", stand_in_libreoffice)
    inputs = setup_input(workspace)
    simple_template(inputs / "t.docx", "Hello {{First Name}}")
    write_csv(inputs / "d.csv", "First Name,Last Name\nAda,Lovelace\nGrace,Hopper\nAlan,Turing\n")

    answer_with(monkeypatch, "y")
    mail_merge.main()

    out = capsys.readouterr().out
    assert [len(c) - c.index("--outdir") - 2 for c in commands] == [2, 1]
    assert all("--headless" in c and c[c.index("--convert-to") + 1] == "pdf" for c in commands)
    assert "Converted 2 of 3 documents..." in out
    assert "Done! Made 3 PDF(s)." in out
    assert "and 3 PDF(s)" in out
    assert (workspace / "merged_documents" / "Alan Turing.pdf").is_file()
    assert len(PdfReader(workspace / "merged_documents" / "All documents.pdf").pages) == 3


def test_combine_pdfs_keeps_every_page_in_order(workspace):
    from pypdf import PdfReader, PdfWriter

    paths = []
    for name, pages in (("a.pdf", 1), ("b.pdf", 2)):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=200, height=100 * pages)
        with open(workspace / name, "wb") as f:
            writer.write(f)
        paths.append(workspace / name)

    mail_merge.combine_pdfs(paths, workspace / "all.pdf")

    heights = [float(page.mediabox.height) for page in PdfReader(workspace / "all.pdf").pages]
    assert heights == [100, 200, 200]


def libreoffice_works():
    soffice = mail_merge.find_libreoffice()
    if not soffice:
        return False
    try:
        return subprocess.run([soffice, "--version"], capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_real_pdf_conversion_with_libreoffice(workspace, monkeypatch, capsys):
    if not libreoffice_works():
        pytest.skip("LibreOffice isn't installed (or doesn't start) on this computer")
    from pypdf import PdfReader

    monkeypatch.setattr(mail_merge, "MAKE_PDFS", True)
    monkeypatch.setattr(mail_merge, "COMBINE_INTO_ONE_PDF", True)
    answer_with(monkeypatch, "y")
    mail_merge.main()  # uses the example certificate and its 3 people

    out = capsys.readouterr().out
    assert "Done! Made 3 PDF(s)." in out
    pdf = workspace / "merged_documents" / "Priya Sharma.pdf"
    assert "Priya Sharma" in PdfReader(pdf).pages[0].extract_text()
    assert len(PdfReader(workspace / "merged_documents" / "All documents.pdf").pages) == 3


def test_first_run_from_the_terminal_without_typing(workspace):
    result = run_script("mail_merge.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "example files were added" in result.stdout
    # Plain-ASCII check: a Windows terminal may not show the dash character
    assert "nothing was created." in result.stdout
    assert output_names(workspace) == []


def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    simple_template(inputs / "award.docx", "Well done, {{First Name}} {{Last Name}}!")
    write_csv(inputs / "winners.csv", "First Name,Last Name\nAda,Lovelace\nGrace,Hopper\n")

    result = run_in_terminal(workspace, "y\n")

    assert result.returncode == 0, result.stderr
    assert "Create 2 documents? Type y to continue:" in result.stdout
    assert "All done!" in result.stdout
    assert "Well done, Grace Hopper!" in document_lines(
        workspace / "merged_documents" / "Grace Hopper.docx"
    )

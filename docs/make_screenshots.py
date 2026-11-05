#!/usr/bin/env python3
"""
Rebuild the screenshots used in the README and tool guides.

Every picture is made from a REAL run: the script prepares sample files in a
temporary folder, runs each tool exactly like a user would, and turns what the
terminal printed into an image. Run it again whenever a tool's messages change.

    pip install -r requirements-dev.txt
    python docs/make_screenshots.py

Needs an internet connection: the sample photo is downloaded from picsum.photos
(Unsplash License, free to use; photo by Alejandro Escamilla), the web scraper
saves two public pages, and the transcriber downloads its speech model once.
The sample meeting recording is made with the macOS `say` command; on other
systems the short test recording is used instead. The Meeting Notes
Summarizer screenshots need the Ollama app open (https://ollama.com).
"""

import csv
import io
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from rich.console import Console, Group
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

# rich ignores the requested width in "dumb" terminals (some editors), which
# squeezes tables; pretend to be a normal terminal so images are always the same.
if os.environ.get("TERM", "dumb") == "dumb":
    os.environ["TERM"] = "xterm-256color"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"
DISPLAY_ROOT = "~/Niche Automation Script Hub"
SAMPLE_PHOTO_URL = "https://picsum.photos/id/0/4032/2688.jpg"
TERMINAL_WIDTH = 92

# Colors applied to recognizable parts of the tools' output
HIGHLIGHTS = [
    (r"^\$ .*$", "bold green"),
    (r"^  Niche Automation Script Hub$", "bold cyan"),
    (r"^  Tool: .*", "bold white"),
    (r"^=+$", "grey42"),
    (r"Done!", "bold green"),
    (r"✓", "bold green"),
    (r"All done!.*", "bold green"),
    (r"⚠️.*", "yellow"),
    (r"📁.*", "grey70"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_tool(script: str, workspace: Path, stdin: str = "", args: tuple = ()) -> str:
    """Run a tool in the sample workspace and return what it printed."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script), *args],
        cwd=workspace,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{result.stdout}\n{result.stderr}")
    # Hide the temporary folder path so screenshots show a normal project path
    output = result.stdout.replace(str(workspace.resolve()), DISPLAY_ROOT)
    output = output.replace(str(workspace), DISPLAY_ROOT)
    return output.strip("\n")


def save_terminal_svg(name: str, command: str, output: str, typed: str = "") -> Path:
    """Render terminal output as a terminal-window SVG image."""
    text = Text(f"$ {command}\n{output}")
    for pattern, style in HIGHLIGHTS:
        text.highlight_regex(re.compile(pattern, re.MULTILINE), style)
    if typed:
        # Make what the user typed at prompts stand out
        for answer in typed.splitlines():
            if answer:
                text.highlight_regex(re.compile(rf"(?<=: ){re.escape(answer)}$", re.MULTILINE), "bold magenta")

    console = Console(record=True, width=TERMINAL_WIDTH, file=io.StringIO())
    console.print(text)
    path = SCREENSHOT_DIR / f"{name}.svg"
    console.save_svg(str(path), title=command)
    print(f"  saved {path.relative_to(PROJECT_ROOT)}")
    return path


def save_tables_svg(name: str, title: str, before: Table, after: Table, arrow: str = "cleaned") -> Path:
    """Render a before/after pair of tables as one SVG image."""
    return save_panel_svg(name, title, [before, Text(f"        ↓  {arrow}", style="bold green"), after])


def save_panel_svg(name: str, title: str, parts: list, width: int = TERMINAL_WIDTH + 18) -> Path:
    """Render any mix of tables, trees and text as one window-style SVG image."""
    console = Console(record=True, width=width, file=io.StringIO())
    console.print(Group(*parts))
    path = SCREENSHOT_DIR / f"{name}.svg"
    console.save_svg(str(path), title=title)
    print(f"  saved {path.relative_to(PROJECT_ROOT)}")
    return path


def show_typed_answers(output: str, answers: list[tuple[str, str]]) -> str:
    """Put what the user typed back after each prompt (typing isn't captured)."""
    for prompt, answer in answers:
        output = output.replace(prompt, f"{prompt}{answer}\n", 1)
    return output


def first_lines(path: Path, count: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[:count])
    return excerpt + ("\n…" if len(lines) > count else "")


def friendly_size(num_bytes: int) -> str:
    kb = num_bytes / 1024
    return f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# One function per tool
# ---------------------------------------------------------------------------

def image_compressor(workspace: Path) -> None:
    inputs = workspace / "input_images"
    inputs.mkdir()

    # Save the sample at normal phone-camera quality, like a real holiday photo
    with urllib.request.urlopen(SAMPLE_PHOTO_URL, timeout=60) as response:
        photo = Image.open(io.BytesIO(response.read())).convert("RGB")
    photo.save(inputs / "desk_photo.jpg", quality=95)

    logo = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse((100, 100, 1100, 1100), fill=(56, 189, 248, 255))
    logo.save(inputs / "team_logo.png")

    output = run_tool("image_compressor.py", workspace)
    save_terminal_svg("image_compressor", "python image_compressor.py", output)

    # Before / after picture
    before_path = inputs / "desk_photo.jpg"
    after_path = workspace / "optimized_images" / "desk_photo.webp"
    with Image.open(before_path) as before, Image.open(after_path) as after:
        before_size, after_size = before.size, after.size
        thumbs = [ImageOps.contain(img.convert("RGB"), (640, 427)) for img in (before, after)]

    labels = [
        ("BEFORE", f"desk_photo.jpg  ·  {friendly_size(before_path.stat().st_size)}  ·  {before_size[0]} × {before_size[1]}"),
        ("AFTER", f"desk_photo.webp  ·  {friendly_size(after_path.stat().st_size)}  ·  {after_size[0]} × {after_size[1]}"),
    ]
    pad, label_h = 24, 70
    canvas = Image.new("RGB", (pad * 3 + 640 * 2, pad * 2 + 427 + label_h), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)
    big, small = load_font(26), load_font(20)
    for i, (thumb, (tag, detail)) in enumerate(zip(thumbs, labels)):
        x = pad + i * (640 + pad)
        canvas.paste(thumb, (x, pad))
        color = (248, 113, 113) if tag == "BEFORE" else (52, 211, 153)
        draw.text((x, pad + 427 + 12), tag, font=big, fill=color)
        draw.text((x, pad + 427 + 44), detail, font=small, fill=(203, 213, 225))
    path = PROJECT_ROOT / "docs" / "assets" / "image_before_after.jpg"
    canvas.save(path, quality=88)
    print(f"  saved {path.relative_to(PROJECT_ROOT)}")


def excel_cleaner(workspace: Path) -> None:
    inputs = workspace / "input_spreadsheets"
    inputs.mkdir()
    rows = [
        ["Order ID", "Customer", "Order Date", "Amount", "Status"],
        ["00117", "Ada Lovelace", "01/15/2024", "£120.00", "Paid"],
        ["00118", "Grace Hopper", "2024-02-03", "£75.50", "N/A"],
        ["00117", "Ada Lovelace", "01/15/2024", "£120.00", "Paid"],
        ["00119", "Alan Turing", "March 5, 2024", "£310.25", "Paid"],
        ["00120", "Katherine Johnson", "15 Apr 2024", "£42.00", "Pending"],
        ["00118", "Grace Hopper", "2024-02-03", "£75.50", "N/A"],
    ]
    with open(inputs / "orders.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    output = run_tool("excel_cleaner.py", workspace)
    save_terminal_svg("excel_cleaner", "python excel_cleaner.py", output)

    with open(workspace / "cleaned_spreadsheets" / "orders_cleaned.csv", encoding="utf-8-sig") as f:
        cleaned = list(csv.reader(f))

    seen, before = set(), Table(title="orders.csv (before)", title_style="bold red", header_style="bold")
    for column in rows[0]:
        before.add_column(column)
    for row in rows[1:]:
        key = tuple(row)
        style = "red strike" if key in seen else None
        seen.add(key)
        before.add_row(*row, style=style)

    after = Table(title="orders_cleaned.csv (after)", title_style="bold green", header_style="bold")
    for column in cleaned[0]:
        after.add_column(column, style="green" if column == "Order Date" else None)
    for row in cleaned[1:]:
        after.add_row(*row)

    save_tables_svg("excel_cleaner_before_after", "Duplicates removed · dates standardized", before, after)


def pdf_extractor(workspace: Path) -> None:
    from fpdf import FPDF

    inputs = workspace / "input_pdfs"
    inputs.mkdir()

    logo = workspace / "logo.png"
    Image.new("RGB", (240, 80), (14, 116, 144)).save(logo)
    chart = workspace / "chart.png"
    chart_img = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(chart_img)
    for i, height in enumerate([120, 170, 150, 230]):
        draw.rectangle((60 + i * 130, 280 - height, 150 + i * 130, 280), fill=(56, 189, 248))
    chart_img.save(chart)

    pages = [
        ("Quarterly Report - Q3", "Revenue grew 12% compared with the previous quarter, "
         "driven by new customers in the retail sector. Operating costs stayed flat."),
        ("Sales by Region", "The North and South regions both beat their targets. "
         "The chart below shows quarterly sales for each of the four regions."),
        ("Next Steps", "1. Hire two account managers.\n2. Launch the spring campaign.\n"
         "3. Review supplier contracts before the end of the year."),
    ]
    pdf = FPDF()
    for heading, body in pages:
        pdf.add_page()
        pdf.image(str(logo), x=150, y=10, w=45)
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 30, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 7, body)
        if heading == "Sales by Region":
            pdf.image(str(chart), x=20, y=80, w=170)
    pdf.output(str(inputs / "quarterly_report.pdf"))

    scan = FPDF()
    scan.add_page()
    receipt = workspace / "receipt.jpg"
    Image.new("RGB", (800, 1100), (245, 240, 230)).save(receipt, quality=90)
    scan.image(str(receipt), x=10, y=10, w=190)
    scan.output(str(inputs / "scanned_receipt.pdf"))

    output = run_tool("pdf_extractor.py", workspace)
    save_terminal_svg("pdf_extractor", "python pdf_extractor.py", output)

    result_dir = workspace / "extracted_pdfs" / "quarterly_report"
    tree = Tree("📁 extracted_pdfs/quarterly_report/", style="bold")
    for item in sorted(result_dir.rglob("*")):
        if item.is_file():
            tree.add(str(item.relative_to(result_dir)), style="cyan")
    excerpt = first_lines(result_dir / "quarterly_report.txt", 12)
    save_panel_svg(
        "pdf_extractor_result",
        "What you get",
        [tree, Text(""), Text("quarterly_report.txt", style="bold"), Text(excerpt, style="grey85")],
    )


def audio_transcriber(workspace: Path) -> None:
    inputs = workspace / "input_audio"
    inputs.mkdir()
    recording = inputs / "team_standup.m4a"
    script = (
        "Good morning everyone, let's keep this stand-up short. "
        "Yesterday I finished the budget spreadsheet and sent it to finance. "
        "Today I'm updating the client presentation for Thursday. "
        "No blockers from me. Next, can we review the hiring plan on Friday?"
    )
    if shutil.which("say") and shutil.which("afconvert"):
        aiff = workspace / "standup.aiff"
        subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", str(aiff), script], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(recording)], check=True)
    else:
        shutil.copy(PROJECT_ROOT / "tests" / "fixtures" / "audio" / "hello.m4a", recording)

    output = run_tool("audio_transcriber.py", workspace)
    save_terminal_svg("audio_transcriber", "python audio_transcriber.py", output)

    transcript = workspace / "transcripts" / "team_standup.txt"
    save_panel_svg(
        "audio_transcriber_result",
        "transcripts/team_standup.txt",
        [Text(first_lines(transcript, 16), style="grey85")],
    )


def bulk_renamer(workspace: Path) -> None:
    folder = workspace / "files_to_rename"
    folder.mkdir()
    names = ["DCIM_9.JPG"] + [f"DCIM_{n:05d}.JPG" for n in range(412, 424)]
    for name in names:
        (folder / name).write_bytes(b"photo")
    before = sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))

    answers = [
        ("Type the new base name (for example Project_Photos): ", "Project Photos"),
        ("Type y to continue: ", "y"),
    ]
    stdin = "".join(answer + "\n" for _, answer in answers)
    output = show_typed_answers(run_tool("bulk_renamer.py", workspace, stdin=stdin), answers)
    save_terminal_svg("bulk_renamer", "python bulk_renamer.py", output, typed=stdin)

    after = sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))
    table = Table(title="files_to_rename/", header_style="bold")
    table.add_column("Before", style="red")
    table.add_column("After", style="green")
    with open(folder / ".rename_undo_log.csv", encoding="utf-8-sig") as f:
        pairs = [(row["old_name"], row["new_name"]) for row in csv.DictReader(f)]
    for old, new in pairs[:6]:
        table.add_row(old, new)
    table.add_row("…", "…")
    save_panel_svg("bulk_renamer_before_after", f"{len(before)} files renamed", [table], width=70)
    assert len(after) == len(before)


def web_scraper(workspace: Path) -> None:
    (workspace / "urls.txt").write_text(
        "# Pages to save\n"
        "https://en.wikipedia.org/wiki/Honey_bee\n"
        "docs.python.org/3/tutorial/introduction.html\n"
        "https://en.wikipedia.org/wiki/This_page_does_not_exist_xyz123\n",
        encoding="utf-8",
    )
    output = run_tool("web_scraper.py", workspace)
    save_terminal_svg("web_scraper", "python web_scraper.py", output)

    saved = sorted((workspace / "scraped_articles").glob("*Python*.md"))
    excerpt = first_lines(saved[0], 18)
    save_panel_svg(
        "web_scraper_result",
        f"scraped_articles/{saved[0].name}",
        [Syntax(excerpt, "markdown", theme="monokai", word_wrap=True, background_color="default")],
    )


def video_subtitles(workspace: Path) -> None:
    inputs = workspace / "input_videos"
    inputs.mkdir()
    video = inputs / "expenses_app_tour.mp4"
    script = (
        "Welcome to this quick tour of the new expenses app. "
        "First, take a photo of your receipt, and the amount and date fill in automatically. "
        "Next, choose the project it belongs to and press submit. "
        "Your manager gets a notification and can approve it straight from their phone. "
        "Any questions? Just send a message to the finance team."
    )
    if shutil.which("say") and shutil.which("ffmpeg"):
        narration = workspace / "narration.aiff"
        subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", str(narration), script], check=True)
        # A plain coloured picture with the narration as its sound track
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=0x0e7490:s=640x360:r=10",
             "-i", str(narration), "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
            check=True,
        )
    else:
        shutil.copy(PROJECT_ROOT / "tests" / "fixtures" / "video" / "hello.mp4", video)

    output = run_tool("video_subtitles.py", workspace)
    save_terminal_svg("video_subtitles", "python video_subtitles.py", output)

    srt = workspace / "subtitles" / f"{video.stem}.srt"
    save_panel_svg(
        "video_subtitles_result",
        f"subtitles/{srt.name}",
        [Text(first_lines(srt, 16), style="grey85")],
    )


def meeting_summarizer(workspace: Path) -> None:
    inputs = workspace / "transcripts"
    inputs.mkdir()
    spoken = [
        ("00:00:00", "Okay, let's get started. This is the weekly sync for the spring product launch."),
        ("00:00:06", "Priya, do you want to start with the website?"),
        ("00:00:10", "Sure. The new landing page is almost done. Only the pricing section is missing, "
                     "because we don't have final prices from finance yet."),
        ("00:00:21", "Tom, can you chase finance for the final prices?"),
        ("00:00:25", "Yes, I'll email Sarah in finance today and ask for them by Wednesday."),
        ("00:00:32", "Next, the launch date. We talked about March 14th or March 21st."),
        ("00:00:39", "The 21st is safer. The video team needs two more weeks for the demo video."),
        ("00:00:46", "Agreed. So we're going with March 21st. Okay, decided."),
        ("00:00:52", "For the email campaign, let's send a sequence of three: a teaser, "
                     "a launch day email and a follow-up a week later."),
        ("00:01:02", "Priya, can you draft the teaser email by next Monday?"),
        ("00:01:06", "Yes, I can do that."),
        ("00:01:09", "Someone also needs to book the photographer for the product shots."),
        ("00:01:14", "I'll take care of it."),
        ("00:01:17", "One open question is the budget for paid social ads. "
                     "We don't know yet if we get five or ten thousand."),
        ("00:01:26", "And do we need legal to review the new claims on the landing page? I'm not sure."),
        ("00:01:33", "Good question. Let's find out. Thanks everyone."),
    ]
    divider = "-" * 60
    transcript = "\n".join(
        [
            "Transcript of:  launch_sync.m4a",
            "Length:         1 min 37 sec",
            "Language:       English (detected automatically, 98% sure)",
            "Speech model:   base",
            "Created on:     2026-03-02 10:15",
            "",
            divider,
            "WITH TIMESTAMPS (hours:minutes:seconds into the recording)",
            divider,
            "",
        ]
        + [f"[{clock}] {line}" for clock, line in spoken]
        + ["", divider, "PLAIN TEXT (ready to copy into an email or document)", divider, ""]
        + [" ".join(line for _, line in spoken)]
    )
    (inputs / "launch_sync.txt").write_text(transcript + "\n", encoding="utf-8")

    # Download the model beforehand so the screenshot shows a normal run
    if shutil.which("ollama"):
        subprocess.run(["ollama", "pull", "llama3.2:3b"], check=True, capture_output=True)

    output = run_tool("meeting_summarizer.py", workspace)
    save_terminal_svg("meeting_summarizer", "python meeting_summarizer.py", output)

    notes = workspace / "meeting_notes" / "launch_sync_notes.md"
    save_panel_svg(
        "meeting_summarizer_result",
        f"meeting_notes/{notes.name}",
        [Syntax(first_lines(notes, 30), "markdown", theme="monokai", word_wrap=True,
                background_color="default")],
    )


def spreadsheet_merger(workspace: Path) -> None:
    from openpyxl import Workbook, load_workbook

    inputs = workspace / "spreadsheets_to_merge"
    inputs.mkdir()
    # Each branch sends its report with slightly different column titles
    branches = {
        "east_branch.csv": [
            ["Order ID", "Order Date", "Amount"],
            ["00305", "2024-03-02", "88.00"],
            [],
            ["Order ID", "Order Date", "Amount"],  # Pasted again by mistake
            ["00306", "2024-03-04", "64.90"],
        ],
        "north_branch.xlsx": [
            ["order id ", "ORDER DATE", "Amount"],
            ["00117", "2024-03-01", 120.0],
            ["00118", "2024-03-02", 75.5],
        ],
        "south_branch.xlsx": [
            ["Order ID", "Order date", "amount", "Discount"],
            ["00201", "2024-03-01", 310.25, "10%"],
            ["00202", "2024-03-03", 42.0, "N/A"],
        ],
        "west_branch.csv": [
            ["Order Id", "order date", "Amount"],
            ["00410", "2024-03-05", "19.99"],
        ],
    }
    for name, rows in branches.items():
        if name.endswith(".csv"):
            with open(inputs / name, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
        else:
            book = Workbook()
            book.active.title = "March"
            for row in rows:
                book.active.append(row)
            book.create_sheet("Notes")  # An empty extra sheet, skipped by the tool
            book.save(inputs / name)

    output = run_tool("spreadsheet_merger.py", workspace)
    save_terminal_svg("spreadsheet_merger", "python spreadsheet_merger.py", output)

    # Before: one small table per input file, two per line
    small_tables = []
    for name, rows in branches.items():
        table = Table(title=name, title_style="bold red", header_style="bold")
        for column in rows[0]:
            table.add_column(column, style="yellow" if column == "Discount" else None)
        for row in rows[1:]:
            if row:
                repeated_header = row == rows[0]
                table.add_row(
                    *[f"{v:.2f}" if isinstance(v, float) else v for v in row],
                    style="red strike" if repeated_header else None,
                )
        small_tables.append(table)
    before = Table.grid(padding=(0, 3))
    for i in range(0, len(small_tables), 2):
        before.add_row(*small_tables[i:i + 2])

    merged_path = next((workspace / "merged_spreadsheets").glob("merged_*.xlsx"))
    sheet = load_workbook(merged_path).active
    after = Table(title=f"{merged_path.name} (after)", title_style="bold green", header_style="bold")
    header = [cell.value for cell in sheet[1]]
    for column in header:
        style = {"Source file": "cyan", "Source sheet": "cyan", "Discount": "yellow"}.get(column)
        after.add_column(column, style=style)
    for cells in sheet.iter_rows(min_row=2):
        shown = []
        for cell in cells:
            if cell.value is None:
                shown.append("")
            elif cell.number_format.startswith("0."):
                shown.append(f"{cell.value:.{len(cell.number_format) - 2}f}")
            else:
                shown.append(str(cell.value))
        after.add_row(*shown)

    save_tables_svg(
        "spreadsheet_merger_before_after",
        f"{len(branches)} branch reports merged into one",
        before,
        after,
        arrow="merged",
    )


def mail_merge(workspace: Path) -> None:
    import contextlib

    sys.path.insert(0, str(PROJECT_ROOT))
    import mail_merge as merge_tool

    inputs = workspace / "mail_merge"
    inputs.mkdir()
    # Use the tool's own example certificate as the template
    with contextlib.redirect_stdout(io.StringIO()):
        merge_tool.create_example_files(inputs)
    (inputs / "example_template.docx").rename(inputs / "training_certificate.docx")
    (inputs / "example_people.csv").unlink()

    rows = [
        ["First Name", "Last Name", "Course", "Date", "Trainer", "Certificate No", "Email"],
        ["Priya", "Sharma", "Excel for Beginners", "14 March 2026", "Sam Taylor", "00041", "priya@example.com"],
        ["Tom", "O'Neill", "First Aid at Work", "21 March 2026", "Alex Morgan", "00042", "tom@example.com"],
        ["Mei", "Chen", "Customer Service Skills", "28 March 2026", "Sam Taylor", "00043", "mei@example.com"],
        ["Daniel", "Okafor", "Excel for Beginners", "14 March 2026", "Sam Taylor", "00044", "daniel@example.com"],
        ["Sofia", "García", "Fire Safety Awareness", "4 April 2026", "Alex Morgan", "00045", "sofia@example.com"],
    ]
    with open(inputs / "attendees.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    answers = [("Type y to continue: ", "y")]
    stdin = "".join(answer + "\n" for _, answer in answers)
    output = show_typed_answers(run_tool("mail_merge.py", workspace, stdin=stdin), answers)
    save_terminal_svg("mail_merge", "python mail_merge.py", output, typed=stdin)

    # A picture of the first finished certificate for the guide (needs LibreOffice)
    first_pdf = workspace / "merged_documents" / "Priya Sharma.pdf"
    if not first_pdf.exists():
        print("  LibreOffice isn't available, so docs/assets/mail_merge_example.png was not updated")
        return
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(first_pdf))
    try:
        image = pdf[0].render(scale=1.5).to_pil().convert("RGB")
    finally:
        pdf.close()
    path = PROJECT_ROOT / "docs" / "assets" / "mail_merge_example.png"
    image.save(path, optimize=True)
    print(f"  saved {path.relative_to(PROJECT_ROOT)}")


# Unsplash License via picsum.photos: mug by Shyamanta Baruah, portrait by Benjamin Combs
BACKGROUND_SAMPLE_PHOTOS = {
    "coffee_mug.jpg": "https://picsum.photos/id/30/1280/901.jpg",
    "portrait.jpg": "https://picsum.photos/id/823/2400/1600.jpg",
}


def checkerboard(size: tuple, square: int = 16) -> Image.Image:
    """The gray-and-white pattern design programs use to show 'see-through'."""
    board = Image.new("RGB", size, (238, 238, 238))
    draw = ImageDraw.Draw(board)
    for y in range(0, size[1], square):
        for x in range((y // square) % 2 * square, size[0], square * 2):
            draw.rectangle((x, y, x + square - 1, y + square - 1), fill=(200, 200, 200))
    return board


def background_remover(workspace: Path) -> None:
    inputs = workspace / "input_photos"
    inputs.mkdir()
    for name, url in BACKGROUND_SAMPLE_PHOTOS.items():
        with urllib.request.urlopen(url, timeout=60) as response:
            Image.open(io.BytesIO(response.read())).convert("RGB").save(inputs / name, quality=95)

    output = run_tool("background_remover.py", workspace)
    # The model is saved in the user's home folder; show it as "~"
    output = output.replace(str(Path.home()), "~")
    save_terminal_svg("background_remover", "python background_remover.py", output)

    # Before / after picture (after on a checkerboard so see-through areas show)
    before_path = inputs / "portrait.jpg"
    after_path = workspace / "no_background" / "portrait.png"
    with Image.open(before_path) as before, Image.open(after_path) as after:
        size = before.size
        before_thumb = ImageOps.contain(before.convert("RGB"), (640, 427))
        after_rgba = ImageOps.contain(after.convert("RGBA"), (640, 427))
        after_thumb = checkerboard(after_rgba.size)
        after_thumb.paste(after_rgba, (0, 0), after_rgba)

    labels = [
        ("BEFORE", f"portrait.jpg  ·  {friendly_size(before_path.stat().st_size)}  ·  {size[0]} × {size[1]}"),
        ("AFTER", f"portrait.png  ·  {friendly_size(after_path.stat().st_size)}  ·  transparent background"),
    ]
    pad, label_h = 24, 70
    canvas = Image.new("RGB", (pad * 3 + 640 * 2, pad * 2 + 427 + label_h), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)
    big, small = load_font(26), load_font(20)
    for i, (thumb, (tag, detail)) in enumerate(zip([before_thumb, after_thumb], labels)):
        x = pad + i * (640 + pad)
        canvas.paste(thumb, (x + (640 - thumb.width) // 2, pad + (427 - thumb.height) // 2))
        color = (248, 113, 113) if tag == "BEFORE" else (52, 211, 153)
        draw.text((x, pad + 427 + 12), tag, font=big, fill=color)
        draw.text((x, pad + 427 + 44), detail, font=small, fill=(203, 213, 225))
    path = PROJECT_ROOT / "docs" / "assets" / "background_before_after.jpg"
    canvas.save(path, quality=88)
    print(f"  saved {path.relative_to(PROJECT_ROOT)}")


def duplicate_finder(workspace: Path) -> None:
    folder = workspace / "files_to_check"
    downloads, pictures, backup = folder / "Downloads", folder / "Pictures", folder / "Phone backup"
    for sub in (downloads, pictures, backup):
        sub.mkdir(parents=True)
    rng = random.Random(7)
    week_ago, today = 1_717_000_000, 1_717_600_000

    def save(path: Path, data: bytes, when: int) -> None:
        path.write_bytes(data)
        os.utime(path, (when, when))

    # Downloaded twice: the browser adds " (1)" to the second copy
    report = rng.randbytes(240 * 1024)
    save(downloads / "report.pdf", report, week_ago)
    save(downloads / "report (1).pdf", report, today)
    invoice = rng.randbytes(96 * 1024)
    save(downloads / "Invoice_March.pdf", invoice, week_ago)
    save(downloads / "Invoice_March (2).pdf", invoice, today)
    save(downloads / "budget.xlsx", rng.randbytes(48 * 1024), week_ago)

    # A holiday video copied to the phone backup as well
    video = rng.randbytes(18 * 1024 * 1024)
    save(downloads / "holiday_video.mp4", video, week_ago)
    save(backup / "holiday_video.mp4", video, today)

    # A photo, exact copies, smaller versions (similar), and a different photo
    with urllib.request.urlopen(SAMPLE_PHOTO_URL, timeout=60) as response:
        photo = Image.open(io.BytesIO(response.read())).convert("RGB")
    photo.save(pictures / "IMG_2041.jpg", quality=92)
    os.utime(pictures / "IMG_2041.jpg", (week_ago, week_ago))
    shutil.copy2(pictures / "IMG_2041.jpg", pictures / "IMG_2041 copy.jpg")
    shutil.copy2(pictures / "IMG_2041.jpg", backup / "IMG_2041.jpg")
    photo.resize((1600, 1067), Image.LANCZOS).save(backup / "IMG_2041_small.jpg", quality=80)
    photo.resize((1008, 672), Image.LANCZOS).save(downloads / "IMG_2041 (emailed).png")
    photo.rotate(180).save(pictures / "IMG_2042.jpg", quality=92)

    answers = [("Type y to continue: ", "y")]
    stdin = "".join(answer + "\n" for _, answer in answers)
    output = show_typed_answers(run_tool("duplicate_finder.py", workspace, stdin=stdin), answers)
    save_terminal_svg("duplicate_finder", "python duplicate_finder.py", output, typed=stdin)


def ocr_reader(workspace: Path) -> None:
    from fpdf import FPDF
    from PIL import ImageFilter

    inputs = workspace / "input_scans"
    inputs.mkdir()
    ink = (28, 28, 30)

    # A café receipt photographed on a desk: slightly tilted and a little soft
    receipt = Image.new("RGB", (900, 1050), (248, 245, 237))
    draw = ImageDraw.Draw(receipt)
    title, body = load_font(56), load_font(36)
    heading = "CORNER CAFÉ"
    draw.text(((900 - draw.textlength(heading, font=title)) / 2, 70), heading, font=title, fill=ink)
    y = 170
    for left, right in [
        ("12 High Street, Leeds", ""),
        ("05/03/2026  10:42", "Table 7"),
        ("", ""),
        ("2 x Flat white", "6.40"),
        ("Almond croissant", "3.20"),
        ("Orange juice", "3.50"),
        ("", ""),
        ("TOTAL", "£13.10"),
        ("Paid by card", "£13.10"),
        ("", ""),
        ("Thank you, see you soon!", ""),
    ]:
        draw.text((80, y), left, font=body, fill=ink)
        draw.text((820 - draw.textlength(right, font=body), y), right, font=body, fill=ink)
        y += 70 if left or right else 50
    desk = Image.new("RGB", (1300, 1400), (122, 96, 72))
    tilted = receipt.rotate(-3, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(122, 96, 72))
    desk.paste(tilted, ((1300 - tilted.width) // 2, (1400 - tilted.height) // 2))
    desk.filter(ImageFilter.GaussianBlur(0.8)).save(inputs / "cafe_receipt.jpg", quality=85)

    # A two-page letter that came back from the scanner as pictures only
    letter_pages = [
        ["Greenfield Lettings", "", "4 March 2026", "", "Dear Ms Patel,", "",
         "Thank you for renewing your tenancy at 18 Elm Road.",
         "Your new agreement starts on 1 April 2026 and runs",
         "for twelve months. The monthly rent stays the same."],
        ["Please sign and return the enclosed copy by",
         "20 March. If anything needs repairing before then,",
         "just reply to this letter or call our office.", "",
         "Yours sincerely,", "", "Daniel Brooks", "Property Manager"],
    ]
    scan = FPDF()
    for number, lines in enumerate(letter_pages, start=1):
        page = Image.new("RGB", (1240, 1754), (250, 250, 247))  # A4 at 150 DPI
        draw = ImageDraw.Draw(page)
        y = 160
        for line in lines:
            font = load_font(44 if line == "Greenfield Lettings" else 30)
            draw.text((130, y), line, font=font, fill=ink)
            y += 56
        draw.text((1060, 1640), f"{number} / {len(letter_pages)}", font=load_font(24), fill=ink)
        page = page.rotate(0.6, resample=Image.Resampling.BICUBIC, fillcolor=(250, 250, 247))
        page_path = workspace / f"letter_page{number}.jpg"
        page.filter(ImageFilter.GaussianBlur(0.5)).save(page_path, quality=80)
        scan.add_page()
        scan.image(str(page_path), x=0, y=0, w=210)
    scan.output(str(inputs / "tenancy_letter.pdf"))

    output = run_tool("ocr_reader.py", workspace)
    save_terminal_svg("ocr_reader", "python ocr_reader.py", output)

    result = workspace / "scanned_text" / "cafe_receipt.txt"
    save_panel_svg(
        "ocr_reader_result",
        "scanned_text/cafe_receipt.txt",
        [Text(first_lines(result, 18), style="grey85")],
    )


TOOLS = {
    "image_compressor.py": image_compressor,
    "ocr_reader.py": ocr_reader,
    "duplicate_finder.py": duplicate_finder,
    "background_remover.py": background_remover,
    "mail_merge.py": mail_merge,
    "spreadsheet_merger.py": spreadsheet_merger,
    "meeting_summarizer.py": meeting_summarizer,
    "video_subtitles.py": video_subtitles,
    "excel_cleaner.py": excel_cleaner,
    "pdf_extractor.py": pdf_extractor,
    "audio_transcriber.py": audio_transcriber,
    "bulk_renamer.py": bulk_renamer,
    "web_scraper.py": web_scraper,
}


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(TOOLS)
    for script in wanted:
        if not (PROJECT_ROOT / script).exists():
            print(f"Skipping {script} (not found)")
            continue
        print(f"Making screenshots for {script} ...")
        workspace = Path(tempfile.mkdtemp(prefix="screens_"))
        try:
            TOOLS[script](workspace)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()

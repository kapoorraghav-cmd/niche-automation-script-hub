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
systems the short test recording is used instead.
"""

import csv
import io
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


TOOLS = {
    "image_compressor.py": image_compressor,
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

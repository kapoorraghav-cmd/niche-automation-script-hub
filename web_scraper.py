#!/usr/bin/env python3
"""
Website-to-Markdown Scraper
===========================
This script saves web articles as clean, easy-to-read Markdown (.md) files.

For every link you give it, it downloads the page, keeps only the main article
(headings, paragraphs, lists, links and tables), and throws away the clutter
around it: menus, adverts, cookie banners, sidebars, footers and comments.
Each article is saved in a "scraped_articles" folder, named after its title.

Where the links come from (the first one that applies wins):
  1. Links typed after the script name, for example:
         python web_scraper.py https://example.com/some-article
  2. A "urls.txt" file in this folder, with one link per line.
  3. Otherwise the script asks you to paste a single link.

Please be respectful: only save pages for your own personal reading, and follow
each website's terms of use and copyright rules. Do not republish what you save.

How to run (after following README.md):
    python web_scraper.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in Python tools, plus trafilatura for finding the article
# ---------------------------------------------------------------------------

import http.client  # Lets us recognise "the connection dropped" errors
import re  # "Regular expressions" — used to tidy up file names
import socket  # Lets us recognise "website not found" and timeout errors
import ssl  # Secure (https://) connections
import sys  # Reads the links typed after the script name
import time  # Lets us pause politely between pages
import unicodedata  # Tidies up accented letters in file names
import urllib.error  # The errors the built-in downloader can raise
import urllib.request  # Python's built-in tool for downloading web pages
import warnings  # Lets us hide one harmless technical warning (see below)
from datetime import date  # Today's date for the "Saved:" line
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional
from urllib.parse import urljoin, urlparse  # Combine and split links

# On some Macs, a helper library prints a scary-looking (but harmless) warning
# about "OpenSSL" every time it loads. Saving articles works fine either way,
# so we hide that one message to keep the output easy to read.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

# trafilatura (installed via: pip install trafilatura)
# It finds the real article inside a busy web page and turns it into Markdown.
# lxml is installed together with trafilatura and reads the page's HTML code.
try:
    import trafilatura
    from lxml import html as lxml_html
    from trafilatura.utils import load_html
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The trafilatura library is not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install trafilatura")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)

# certifi is installed together with trafilatura. It is an up-to-date list of
# trusted website certificates, which avoids "certificate verify failed"
# errors on computers (especially Macs) whose own list is missing or old.
try:
    import certifi
except ImportError:
    certifi = None


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where THIS SCRIPT saves the finished .md files
OUTPUT_FOLDER_NAME = "scraped_articles"

# Optional list of links, one per line (lines starting with # are ignored)
URLS_FILE_NAME = "urls.txt"

# How long to wait for a website to answer before giving up (in seconds)
TIMEOUT_SECONDS = 20

# Pause between pages so we never flood a website with requests (in seconds)
DELAY_BETWEEN_PAGES_SECONDS = 1

# Skip anything bigger than this. Normal article pages are well under 5 MB.
MAX_PAGE_MB = 20

# If the article we find is shorter than this many characters, it is almost
# certainly not a real article (for example a "please enable JavaScript" or
# "please log in" message), so we skip it instead of saving an empty file.
MIN_ARTICLE_CHARACTERS = 200

# Keep clickable links inside the saved article? (True = yes, False = plain text)
KEEP_LINKS = True

# On some pages (Wikipedia especially) keeping links makes the article
# extractor drop words or chop sentences into pieces. We compare against a
# links-free copy and only keep the links if at least this share of the
# words survived (0.97 = 97%); otherwise we save the complete text without links.
LINKS_MIN_WORD_SHARE = 0.97

# Longest file name we create (before ".md"). Very long names cause trouble
# on Windows and in cloud storage folders.
MAX_FILENAME_LENGTH = 80

# Some pages put menus or long lists in their "author" field by mistake.
# A real author line is short, so anything longer than this is left out.
MAX_AUTHOR_LENGTH = 80

# Small page parts to always remove (written in "XPath", a way to point at
# parts of a web page). This removes Wikipedia's "[edit]" labels on headings.
REMOVE_PAGE_PARTS = "//*[contains(@class,'mw-editsection')]"

# Many websites refuse requests that don't look like they come from a normal
# web browser, so we introduce ourselves like a regular desktop browser.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Text written at the top of a new urls.txt file to explain how to use it
URLS_FILE_HEADER = """\
# Put the web links you want to save in this file, one link per line.
# Lines starting with # (like this one) and blank lines are ignored.
# You can leave out "https://" — the script adds it for you.
#
# Example:
# https://en.wikipedia.org/wiki/Honey_bee
#
# Please only save pages for your own personal reading, and respect each
# website's terms of use and copyright.
"""

# Characters Windows does not allow in file names (macOS and Linux are less
# strict, so following the Windows rules keeps the files usable everywhere).
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Names Windows reserves for devices. A file called "CON.md" cannot be created.
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}

# Characters that separate an article title from the site name, as in
# "Honey bee - Wikipedia" or "Budget news | The Daily Paper"
TITLE_SEPARATORS = {"-", "|", "–", "—", ":", "·", "•"}

# A Markdown link looks like [link text](https://address)
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")

# A paragraph that is nothing but one link (plus maybe a comma or full stop)
LONELY_LINK_PARAGRAPH = re.compile(r"\[[^\]]*\]\([^)\s]*\)[^\w\[]{0,3}")

# The little "¶" or "#" links many sites put next to headings to share a
# section. They mean nothing in a saved file, so we remove them.
HEADING_PERMALINK = re.compile(r"\[(?:¶|§|#|🔗)\]\([^)\s]*\)")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class FriendlyError(Exception):
    """A problem we can explain in plain English, so we skip the link politely."""


class Article(NamedTuple):
    """Everything we found on one web page."""

    title: str
    markdown: str  # The article itself, in Markdown
    author: Optional[str]
    published: Optional[str]  # Date like 2024-03-14, when the page says
    links_kept: bool  # False if links were left out to keep all the text


def normalize_url(text: str) -> Optional[str]:
    """
    Turn whatever the user typed into a proper web link, or None if it
    clearly isn't one.

        example.com/article        →  https://example.com/article
        http://example.com         →  http://example.com   (kept as typed)
        hello there                →  None
    """
    # Remove spaces and the <...> or "..." people sometimes copy along with a link
    link = text.strip().strip("<>\"'").strip()
    if not link or any(character.isspace() for character in link):
        return None

    if not link.lower().startswith(("http://", "https://")):
        # A different kind of link (like ftp:// or mailto:) can't be saved
        if "://" in link or link.lower().startswith(("mailto:", "file:", "javascript:")):
            return None
        link = "https://" + link

    try:
        host = urlparse(link).hostname or ""
    except ValueError:  # Badly broken links, like "https://[oops"
        return None
    # A real website address has a dot in it (example.com) — or is "localhost"
    if "." not in host and host != "localhost":
        return None
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return None
    return link


def read_urls_file(path: Path) -> list[str]:
    """
    Read links from urls.txt, skipping blank lines and # comments.
    Lines that don't look like links are reported and skipped.
    """
    links = []
    # utf-8-sig quietly removes the invisible marker Notepad sometimes adds
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        link = normalize_url(line)
        if link:
            links.append(link)
        else:
            print(f"   ⚠️  Skipped line {line_number} in {path.name} — "
                  f"that doesn't look like a web link: {line}")
    return links


def create_urls_file(path: Path) -> None:
    """Create an example urls.txt so the user knows how to use it next time."""
    path.write_text(URLS_FILE_HEADER, encoding="utf-8")
    print(f"📝 Created {path.name} — next time you can list many links in it, one per line.")
    print()


def ask_for_link(max_tries: int = 3) -> Optional[str]:
    """
    Ask the user to paste one link. If what they type doesn't look like a
    link, explain and ask again (a few times at most).
    """
    for _ in range(max_tries):
        try:
            answer = input("Paste a web link and press Enter (or just press Enter to quit): ")
        except EOFError:
            # Nothing can be typed (for example when run by another program)
            return None

        if not answer.strip():
            return None

        link = normalize_url(answer)
        if link:
            return link
        print("   Hmm, that doesn't look like a web link. "
              "Try something like: https://example.com/article")
    return None


def collect_links(command_line_args: list[str]) -> list[str]:
    """
    Gather the links to save, in this order of priority:
      1. Links typed after the script name
      2. The urls.txt file
      3. Asking the user to paste one link
    Duplicate links are only saved once.
    """
    links: list[str] = []

    if command_line_args:
        print("Using the link(s) you typed after the script name.")
        for argument in command_line_args:
            link = normalize_url(argument)
            if link:
                links.append(link)
            else:
                print(f"   ⚠️  Skipped — that doesn't look like a web link: {argument}")
    else:
        urls_file = Path(".") / URLS_FILE_NAME
        if urls_file.exists():
            print(f"📄 Reading links from {urls_file.resolve()}")
            links = read_urls_file(urls_file)
            if not links:
                print(f"   No links found in {urls_file.name} yet.")
                print()
        else:
            create_urls_file(urls_file)

        if not links:
            link = ask_for_link()
            if link:
                links.append(link)

    # dict.fromkeys removes repeats but keeps the original order
    return list(dict.fromkeys(links))


def make_ssl_context() -> ssl.SSLContext:
    """Secure-connection settings that use certifi's certificate list when available."""
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def explain_http_error(code: int, reason: str) -> str:
    """Turn a website's error number into a plain-English explanation."""
    if code in (404, 410):
        return (f"the page was not found (error {code}). Check the link for typos — "
                "the page may have moved or been deleted.")
    if code in (401, 403):
        return (f"the website refused access (error {code}). Some sites block "
                "automatic downloads or need you to log in — open it in your browser instead.")
    if code == 429:
        return "the website says we asked too often (error 429). Wait a few minutes and try again."
    if code >= 500:
        return f"the website is having problems right now (error {code}). Try again later."
    return f"the website answered with error {code} ({reason})."


def explain_connection_problem(reason: object) -> str:
    """Explain why we couldn't reach a website at all."""
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return (f"the website took too long to answer (more than {TIMEOUT_SECONDS} seconds). "
                "Try again later.")
    if isinstance(reason, socket.gaierror):
        return ("could not find this website. Check your internet connection "
                "and the spelling of the link.")
    if isinstance(reason, ssl.SSLError):
        return ("the website's security certificate could not be checked, "
                "so it was skipped to keep you safe.")
    if isinstance(reason, ConnectionRefusedError):
        return "the website could not be reached (connection refused). It may be down right now."
    return f"could not connect to the website ({reason}). Check your internet connection."


def download_page(url: str) -> tuple[bytes, str, str]:
    """
    Download one web page.
    Returns (page contents, final link after any redirects, content type).

    We use Python's built-in downloader (urllib) rather than trafilatura's own,
    because it tells us exactly WHY a download failed (404, 403, timeout,
    no internet...) and what kind of file came back (web page or PDF), so we
    can print a helpful message instead of a vague "it didn't work".
    """
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    max_bytes = MAX_PAGE_MB * 1024 * 1024

    try:
        with urllib.request.urlopen(
            request, timeout=TIMEOUT_SECONDS, context=make_ssl_context()
        ) as response:
            content_type = response.headers.get_content_type()
            # Read one byte more than the limit so we can tell if it's too big
            body = response.read(max_bytes + 1)
            final_url = response.geturl()
    except urllib.error.HTTPError as err:
        raise FriendlyError(explain_http_error(err.code, str(err.reason))) from err
    except urllib.error.URLError as err:
        raise FriendlyError(explain_connection_problem(err.reason)) from err
    except (socket.timeout, TimeoutError) as err:
        raise FriendlyError(explain_connection_problem(err)) from err
    except (http.client.HTTPException, ConnectionError) as err:
        raise FriendlyError(
            "the connection dropped while downloading. Check your internet and try again."
        ) from err

    if len(body) > max_bytes:
        raise FriendlyError(f"this page is bigger than {MAX_PAGE_MB} MB, so it was skipped.")

    return body, final_url, content_type


def check_is_web_page(body: bytes, content_type: str) -> None:
    """Stop early with a clear message if the link is a PDF or other non-web-page file."""
    # Every PDF file starts with the letters "%PDF-", whatever the website calls it
    if content_type == "application/pdf" or body[:5] == b"%PDF-":
        raise FriendlyError(
            "this link is a PDF file, not a web page. Open it in your browser "
            "or PDF reader and save it from there instead."
        )

    if content_type in ("text/html", "application/xhtml+xml"):
        return

    # Some websites label their pages wrongly, so peek at the start of the file
    start = body[:1000].lstrip().lower()
    if start.startswith(b"<!doctype html") or b"<html" in start:
        return

    raise FriendlyError(
        f"this link opens a '{content_type}' file, not a web page, so there is no article to save."
    )


def title_from_link(url: str) -> str:
    """Make a fallback title from the link, e.g. .../honey-bees → 'honey bees'."""
    parts = urlparse(url)
    last_piece = parts.path.rstrip("/").rsplit("/", 1)[-1]
    last_piece = re.sub(r"\.(html?|php|aspx?)$", "", last_piece, flags=re.IGNORECASE)
    words = re.sub(r"[-_+]+", " ", last_piece).strip()
    return words or parts.hostname or "article"


def safe_filename(title: str, fallback: str = "article") -> str:
    """
    Turn an article title into a file name that works on Windows, macOS and Linux.

        'Q&A: What is "honey"?'  →  'Q&A - What is honey'
    """
    # Combine accented letters into one character so names look the same everywhere
    name = unicodedata.normalize("NFC", title)
    # A colon in a title usually separates two parts, so make it a dash
    name = name.replace(":", " -")
    # Turn tabs and line breaks into single spaces before removing bad characters
    name = re.sub(r"\s+", " ", name)
    name = INVALID_FILENAME_CHARACTERS.sub("", name)
    name = re.sub(r" +", " ", name).strip()

    if len(name) > MAX_FILENAME_LENGTH:
        # Cut at a word boundary when possible so names don't end mid-word
        cut = name[:MAX_FILENAME_LENGTH]
        if " " in cut[MAX_FILENAME_LENGTH // 2:]:
            cut = cut.rsplit(" ", 1)[0]
        name = cut

    # Windows does not allow names ending in a dot or space, and on macOS and
    # Linux a name starting with a dot becomes a hidden file
    name = name.strip(". ")

    if not name:
        name = fallback
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        name = f"{name}_article"
    return name


def choose_destination(title: str, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick a file name that never overwrites another article:
    'Honey Bees.md', then 'Honey Bees_2.md', 'Honey Bees_3.md', ...

    used_names holds lowercase names, because Windows and macOS treat
    'Honey.md' and 'honey.md' as the same file.
    """
    base = safe_filename(title)
    candidate = f"{base}.md"
    number = 2
    while candidate.lower() in used_names:
        candidate = f"{base}_{number}.md"
        number += 1
    used_names.add(candidate.lower())
    return output_dir / candidate


def remove_repeated_title(markdown: str, title: str) -> str:
    """Many pages repeat the title as their first heading — drop it, we add our own."""
    lines = markdown.lstrip().splitlines()
    if lines and lines[0].lstrip("#").strip().lower() == title.strip().lower():
        return "\n".join(lines[1:]).lstrip()
    return markdown.strip()


def make_links_absolute(body: bytes, url: str):
    """
    Rewrite every link in the page as a full web address.

    Pages often use short links like "glossary.html" or "#section-2" that only
    work while you are on that page. trafilatura completes them using the
    website's front page instead of the article's own address, which breaks
    many of them, so we complete them correctly first.
    Returns the page as text, or the original bytes if it can't be read.
    """
    tree = load_html(body)
    if tree is None:
        return body

    # A <base href="..."> tag tells browsers to complete links from a different address
    base = url
    for base_tag in tree.xpath("//base[@href]"):
        try:
            base = urljoin(url, base_tag.get("href"))
        except ValueError:
            pass
        break

    def complete(link: str) -> str:
        try:
            return urljoin(base, link)
        except ValueError:
            return link  # A broken link stays as it was

    tree.rewrite_links(complete, resolve_base_href=False)
    return lxml_html.tostring(tree, encoding="unicode")


def extract_markdown(page, url: str, include_links: bool) -> str:
    """Ask trafilatura for the main article as Markdown ("" if none was found)."""
    markdown = trafilatura.extract(
        page,
        url=url,
        output_format="markdown",
        include_links=include_links,  # keep [link text](address) links
        include_tables=True,
        include_formatting=True,  # keep bold/italic text and headings
        include_comments=False,  # reader comments below articles are skipped
        include_images=False,  # images would only be links to the website anyway
        prune_xpath=REMOVE_PAGE_PARTS,
    )
    return HEADING_PERMALINK.sub("", markdown or "")


def count_words(markdown: str) -> int:
    """Count the words a reader sees (link addresses don't count)."""
    return len(MARKDOWN_LINK.sub(r"\1", markdown).split())


def looks_chopped_up(markdown: str) -> bool:
    """True if many paragraphs are just a single link — a sign sentences were cut apart."""
    paragraphs = [block.strip() for block in markdown.split("\n\n") if block.strip()]
    lonely = sum(1 for block in paragraphs if LONELY_LINK_PARAGRAPH.fullmatch(block))
    return lonely >= 5 and lonely > len(paragraphs) * 0.10


def best_markdown(page, url: str) -> tuple[str, bool]:
    """
    Get the article with links when that is safe, otherwise without them.
    Returns (markdown, whether links were kept).

    Complete text matters more than links, so the links-free copy is the
    safety net whenever the linked copy lost words or looks chopped up.
    """
    without_links = extract_markdown(page, url, include_links=False)
    if not KEEP_LINKS:
        return without_links, False

    with_links = extract_markdown(page, url, include_links=True)
    if with_links and not looks_chopped_up(with_links) and (
        count_words(with_links) >= count_words(without_links) * LINKS_MIN_WORD_SHARE
    ):
        return with_links, True
    if without_links:
        return without_links, False
    return with_links, True


def first_heading(markdown: str) -> Optional[str]:
    """The text of the first Markdown heading (# Like this), if there is one."""
    match = re.search(r"^#{1,6}\s+(.+)$", markdown, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def extract_article(body: bytes, url: str) -> Article:
    """Find the main article in the page, plus its title, author and date."""
    try:
        page = make_links_absolute(body, url)
    except Exception:
        page = body  # Fixing links is a nice extra, never a reason to skip a page
    markdown, links_kept = best_markdown(page, url)

    if len(markdown.strip()) < MIN_ARTICLE_CHARACTERS:
        raise FriendlyError(
            "no article text could be found on this page. It may be built with "
            "JavaScript, need a login, or be behind a paywall — open it in your browser instead."
        )

    metadata = trafilatura.extract_metadata(page, default_url=url)
    title = re.sub(r"\s+", " ", (metadata.title if metadata else None) or "").strip()
    heading = first_heading(markdown)
    if not title:
        # No title on the page? Use the first heading, or the link itself
        title = heading or title_from_link(url)
    elif heading and title.lower().startswith(heading.lower()):
        # Page titles often add the site name ("Honey bee - Wikipedia"), while
        # the article's own heading is just "Honey bee" — use the cleaner one
        leftover = title[len(heading):].strip()
        if leftover[:1] in TITLE_SEPARATORS:
            title = heading

    author = metadata.author if metadata else None
    if author and len(author) > MAX_AUTHOR_LENGTH:
        author = None

    return Article(
        title=title,
        markdown=remove_repeated_title(markdown, title),
        author=author,
        published=metadata.date if metadata else None,
        links_kept=links_kept,
    )


def build_markdown_file(article: Article, url: str) -> str:
    """Put together the finished .md file: title, source details, then the article."""
    # The details are a bulleted list so every Markdown viewer (including
    # GitHub) shows them on separate lines instead of running them together.
    lines = [
        f"# {article.title}",
        "",
        f"- Source: {url}",
        f"- Saved: {date.today().isoformat()}",
    ]
    if article.author:
        lines.append(f"- Author: {article.author}")
    if article.published:
        lines.append(f"- Published: {article.published}")
    lines += ["", article.markdown.strip(), ""]
    return "\n".join(lines)


def save_one_page(
    url: str, output_dir: Path, index: int, total: int, used_names: set[str]
) -> bool:
    """Download → extract → save one page, with friendly progress messages.
    Returns True if the article was saved."""
    print(f"Saving page {index} of {total}: {url} ...")

    try:
        body, final_url, content_type = download_page(url)
        check_is_web_page(body, content_type)
        article = extract_article(body, final_url)

        destination = choose_destination(article.title, output_dir, used_names)
        # Build the whole file first, then write it in one go, so a problem
        # never leaves a half-finished file behind.
        destination.write_text(build_markdown_file(article, final_url), encoding="utf-8")
    except FriendlyError as err:
        print(f"   ⚠️  Skipped this link — {err}")
        print()
        return False
    except Exception as err:
        # Don't crash the whole batch if one page fails in an unexpected way
        print(f"   ⚠️  Skipped this link — something went wrong: {err}")
        print()
        return False

    print(f"   Done! \"{article.title}\" (about {count_words(article.markdown):,} words)")
    if KEEP_LINKS and not article.links_kept:
        print("   Note: links were left out on this page so that no text would be lost.")
    print(f"   Saved as: {destination.name}")
    print()
    return True


# ---------------------------------------------------------------------------
# Main program — runs when you type: python web_scraper.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Website-to-Markdown Scraper")
    print("=" * 60)
    print()
    print("Please only save pages for your own personal reading, and respect")
    print("each website's terms of use and copyright.")
    print()

    links = collect_links(sys.argv[1:])

    if not links:
        print()
        print("No links to save yet.")
        print()
        print("What to do next (pick one):")
        print("  • Type a link after the script name:")
        print()
        print("         python web_scraper.py https://example.com/article")
        print()
        print(f"  • Or add links to '{URLS_FILE_NAME}' (one per line) and run:")
        print()
        print("         python web_scraper.py")
        print()
        return

    output_dir = Path(".") / OUTPUT_FOLDER_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    total = len(links)
    print(f"Found {total} link(s) to save. Starting now...")
    print()

    # Lowercase names already in the folder, so we never overwrite an older save
    used_names = {item.name.lower() for item in output_dir.iterdir()}
    saved = 0

    for i, link in enumerate(links, start=1):
        if i > 1:
            # A short pause between pages is kinder to the websites we visit
            time.sleep(DELAY_BETWEEN_PAGES_SECONDS)
        if save_one_page(link, output_dir, i, total, used_names):
            saved += 1

    print("=" * 60)
    print(f"All done! Saved {saved} of {total} page(s).")
    print(f"Check the '{OUTPUT_FOLDER_NAME}' folder for your .md files.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

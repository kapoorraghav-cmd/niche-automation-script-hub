"""Tests for web_scraper.py — fully offline, using a tiny local web server."""

import socket
import sys
import threading
import urllib.error
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import web_scraper
from conftest import run_script

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "web"
ARTICLE_HTML = (FIXTURES / "article.html").read_bytes()
JAVASCRIPT_ONLY_HTML = (FIXTURES / "javascript_only.html").read_bytes()
WIKI_STYLE_HTML = (FIXTURES / "wiki_style.html").read_bytes()
TITLE = "How Bees Make Honey"

# Path on the local server → (status code, content type, page contents)
PAGES = {
    "/article": (200, "text/html; charset=utf-8", ARTICLE_HTML),
    "/article-copy": (200, "text/html; charset=utf-8", ARTICLE_HTML),
    "/blog/2024/bees": (200, "text/html; charset=utf-8", ARTICLE_HTML),
    "/wiki/Garden_snail": (200, "text/html; charset=utf-8", WIKI_STYLE_HTML),
    "/app": (200, "text/html; charset=utf-8", JAVASCRIPT_ONLY_HTML),
    "/report.pdf": (200, "application/pdf", b"%PDF-1.4\n%fake pdf for testing\n"),
    "/data.json": (200, "application/json", b'{"hello": "world"}'),
    "/members-only": (403, "text/html", b"<html><body>Forbidden</body></html>"),
}


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, content_type, body = PAGES.get(
            self.path, (404, "text/html", b"<html><body>Not found</body></html>")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Keep the test output quiet


@pytest.fixture(scope="module")
def server():
    """Start a local web server on 127.0.0.1 and return its base address."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    """No pause between pages, no proxy for the local server, no pytest arguments."""
    monkeypatch.setattr(web_scraper, "DELAY_BETWEEN_PAGES_SECONDS", 0)
    monkeypatch.setattr(sys, "argv", ["web_scraper.py"])
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")


def run_with_links(monkeypatch, *links):
    monkeypatch.setattr(sys, "argv", ["web_scraper.py", *links])
    web_scraper.main()


def saved_files(workspace):
    return sorted(p.name for p in (workspace / "scraped_articles").iterdir())


def read_article(workspace, name=f"{TITLE}.md"):
    return (workspace / "scraped_articles" / name).read_text(encoding="utf-8")


def test_article_is_kept_and_page_clutter_is_removed(workspace, monkeypatch, server):
    run_with_links(monkeypatch, f"{server}/article")

    text = read_article(workspace)
    # Article text, headings, lists, links and tables survive
    assert "Forager bees visit hundreds of flowers" in text
    assert "## Step one: collecting nectar" in text
    assert "### What a single hive produces" in text
    assert "- Finished honey holds less than twenty percent water." in text
    assert "](https://example.org/bees)" in text
    assert "| Spring | 5 kg |" in text
    # Menus, adverts, cookie banner, comments, sidebar and footer are gone
    for junk in (
        "cookies",
        "Latest News",
        "GARDEN GNOMES",
        "crypto",
        "Trending this week",
        "newsletter",
        "All rights reserved",
    ):
        assert junk.lower() not in text.lower(), junk


def test_short_links_are_completed_from_the_article_address(workspace, monkeypatch, server):
    run_with_links(monkeypatch, f"{server}/blog/2024/bees")

    text = read_article(workspace)
    assert f"[hive tools guide]({server}/blog/2024/hive-tools.html)" in text
    # The "¶" share-this-section link next to the heading is removed
    assert "¶" not in text
    assert "## Step one: collecting nectar\n" in text


def test_file_starts_with_title_source_date_and_author(workspace, monkeypatch, server):
    run_with_links(monkeypatch, f"{server}/article")

    lines = read_article(workspace).splitlines()
    assert lines[0] == f"# {TITLE}"
    assert f"- Source: {server}/article" in lines
    assert f"- Saved: {date.today().isoformat()}" in lines
    assert "- Author: Maya Fernandes" in lines
    assert "- Published: 2024-03-14" in lines
    # The page's own copy of the title heading is not repeated
    assert lines.count(f"# {TITLE}") == 1


def test_no_text_is_lost_on_pages_that_break_link_keeping(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/wiki/Garden_snail")

    text = read_article(workspace, "Garden snail.md")
    assert text.startswith("# Garden snail\n")
    # The end of every sentence survives (trafilatura drops these when keeping links)
    assert "protects its foot from sharp stones." in text
    assert "keeps moisture inside until conditions improve again." in text
    assert "## Behaviour" in text
    assert "edit]" not in text
    assert "Random article" not in text
    assert "links were left out" in capsys.readouterr().out


def test_links_are_kept_when_nothing_is_lost(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/article")

    assert "links were left out" not in capsys.readouterr().out


def test_looks_chopped_up_spots_link_only_paragraphs():
    tidy = "\n\n".join(["A sentence with a [link](https://x.org) inside."] * 10)
    chopped = "\n\n".join(["Start of a sentence", "[word](https://x.org),"] * 5)

    assert not web_scraper.looks_chopped_up(tidy)
    assert web_scraper.looks_chopped_up(chopped)


def make_page(title_tag, heading, author=""):
    paragraph = "<p>" + "This sentence is part of a long enough article body. " * 8 + "</p>"
    meta = f'<meta property="og:title" content="{title_tag}">'
    if author:
        meta += f'<meta name="author" content="{author}">'
    return (
        f"<html><head><title>{title_tag}</title>{meta}</head><body><article>"
        f"<h1>{heading}</h1>{paragraph}{paragraph}</article></body></html>"
    ).encode()


@pytest.mark.parametrize(
    "title_tag, heading, expected",
    [
        ("Honey bee - Wikipedia", "Honey bee", "Honey bee"),
        ("Budget news | The Daily Paper", "Budget news", "Budget news"),
        ("Python 3.12 release notes", "Python", "Python 3.12 release notes"),
    ],
)
def test_site_name_is_trimmed_from_titles(title_tag, heading, expected):
    article = web_scraper.extract_article(make_page(title_tag, heading), "https://example.com/a")

    assert article.title == expected


def test_suspiciously_long_author_is_left_out():
    long_author = "Authority control databases International National Libraries " * 3
    article = web_scraper.extract_article(
        make_page("Some story", "Some story", author=long_author), "https://example.com/a"
    )

    assert article.author is None


def test_files_are_named_from_the_title_without_overwriting(workspace, monkeypatch, server):
    output = workspace / "scraped_articles"
    output.mkdir()
    (output / f"{TITLE}.md").write_text("an older save", encoding="utf-8")

    run_with_links(monkeypatch, f"{server}/article", f"{server}/article-copy")

    assert saved_files(workspace) == [f"{TITLE}.md", f"{TITLE}_2.md", f"{TITLE}_3.md"]
    assert read_article(workspace) == "an older save"


def test_same_link_twice_is_only_saved_once(workspace, monkeypatch, server):
    run_with_links(monkeypatch, f"{server}/article", f"{server}/article")

    assert saved_files(workspace) == [f"{TITLE}.md"]


def test_missing_page_is_skipped_and_the_batch_continues(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/does-not-exist", f"{server}/article")

    out = capsys.readouterr().out
    assert "Skipped this link — the page was not found (error 404)" in out
    assert "Saved 1 of 2 page(s)" in out
    assert saved_files(workspace) == [f"{TITLE}.md"]


def test_forbidden_page_gets_a_friendly_message(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/members-only")

    assert "the website refused access (error 403)" in capsys.readouterr().out
    assert saved_files(workspace) == []


def test_javascript_only_page_is_explained_not_saved(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/app")

    assert "no article text could be found" in capsys.readouterr().out
    assert saved_files(workspace) == []


def test_pdf_and_other_files_are_skipped(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/report.pdf", f"{server}/data.json")

    out = capsys.readouterr().out
    assert "this link is a PDF file" in out
    assert "'application/json' file, not a web page" in out
    assert saved_files(workspace) == []


def test_unreachable_website_is_explained(workspace, monkeypatch, capsys):
    # Grab a free port, then close it so nothing is listening there
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]

    run_with_links(monkeypatch, f"http://127.0.0.1:{closed_port}/article")

    assert "Skipped this link — the website could not be reached" in capsys.readouterr().out


def test_no_internet_is_explained(workspace, monkeypatch, capsys):
    def no_internet(*args, **kwargs):
        raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))

    monkeypatch.setattr(web_scraper.urllib.request, "urlopen", no_internet)
    run_with_links(monkeypatch, "example.com/news")

    out = capsys.readouterr().out
    assert "could not find this website. Check your internet connection" in out
    assert "All done!" in out


def test_output_folder_is_created(workspace, monkeypatch, server, capsys):
    run_with_links(monkeypatch, f"{server}/article")

    assert (workspace / "scraped_articles").is_dir()
    assert "Output folder ready" in capsys.readouterr().out


def test_links_are_read_from_urls_txt(workspace, server, capsys):
    (workspace / "urls.txt").write_text(
        "# My reading list\n"
        "\n"
        f"   {server}/article   \n"
        "# another comment\n"
        "not a link at all\n"
        "\n"
        f"{server}/article-copy\n",
        encoding="utf-8",
    )

    web_scraper.main()

    out = capsys.readouterr().out
    assert "Skipped line 5 in urls.txt" in out
    assert "Found 2 link(s) to save" in out
    assert saved_files(workspace) == [f"{TITLE}.md", f"{TITLE}_2.md"]


def test_read_urls_file_ignores_comments_and_blank_lines(workspace):
    path = workspace / "urls.txt"
    path.write_text("\ufeff# header\n\nexample.com/a\n  # indented comment\nhttp://x.org\n",
                    encoding="utf-8")

    assert web_scraper.read_urls_file(path) == ["https://example.com/a", "http://x.org"]


def test_command_line_links_win_over_urls_txt(workspace, monkeypatch, server):
    (workspace / "urls.txt").write_text(f"{server}/article-copy\n{server}/app\n",
                                        encoding="utf-8")

    run_with_links(monkeypatch, f"{server}/article")

    assert saved_files(workspace) == [f"{TITLE}.md"]


def test_asks_for_a_link_and_creates_urls_txt(workspace, monkeypatch, server, capsys):
    answers = iter(["hello there", f"{server}/article"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    web_scraper.main()

    out = capsys.readouterr().out
    assert "doesn't look like a web link" in out
    assert saved_files(workspace) == [f"{TITLE}.md"]
    assert (workspace / "urls.txt").read_text(encoding="utf-8").startswith("# Put the web links")


def test_pressing_enter_without_a_link_quits_politely(workspace, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    web_scraper.main()

    assert "No links to save yet." in capsys.readouterr().out
    assert not (workspace / "scraped_articles").exists()


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("example.com/article", "https://example.com/article"),
        ("www.example.com", "https://www.example.com"),
        ("  https://example.com/a?b=1  ", "https://example.com/a?b=1"),
        ("<https://example.com>", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("HTTPS://Example.com/Page", "HTTPS://Example.com/Page"),
        ("http://localhost:8000/page", "http://localhost:8000/page"),
        ("", None),
        ("hello there", None),
        ("notalink", None),
        ("ftp://example.com/file", None),
        ("mailto:someone@example.com", None),
        ("http//example.com", None),
        ("https://[oops", None),
    ],
)
def test_normalize_url_adds_https_and_rejects_bad_input(typed, expected):
    assert web_scraper.normalize_url(typed) == expected


@pytest.mark.parametrize(
    "title, expected",
    [
        ('Q&A: What is "honey"?', "Q&A - What is honey"),
        ("Cats/Dogs <Part 1|2>", "CatsDogs Part 12"),
        ("Ends with dots...", "Ends with dots"),
        (".hidden title", "hidden title"),
        ("CON", "CON_article"),
        ("???", "article"),
        ("  lots   of\tspace  ", "lots of space"),
        ("Café crème", "Café crème"),
    ],
)
def test_safe_filename_works_on_every_computer(title, expected):
    assert web_scraper.safe_filename(title) == expected


def test_safe_filename_limits_length():
    name = web_scraper.safe_filename("word " * 100)

    assert 0 < len(name) <= web_scraper.MAX_FILENAME_LENGTH
    assert not name.endswith(" ")


def test_runs_from_the_terminal(workspace, server):
    (workspace / "urls.txt").write_text(
        f"# Links for the terminal test\n\n{server}/article\n{server}/missing\n",
        encoding="utf-8",
    )

    result = run_script("web_scraper.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Tool: Website-to-Markdown Scraper" in result.stdout
    assert "Saving page 1 of 2" in result.stdout
    assert "error 404" in result.stdout
    assert "All done! Saved 1 of 2 page(s)." in result.stdout
    assert saved_files(workspace) == [f"{TITLE}.md"]
    assert read_article(workspace).startswith(f"# {TITLE}\n")

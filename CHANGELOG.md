# Changelog

All notable changes to this project are listed here.

## [1.1.0] — 2026-11-07

### No Python install needed
- The double-click launchers now set everything up by themselves: on first run they download [uv](https://docs.astral.sh/uv/) and a private copy of Python into the hub's folder (about 40 MB). Nothing else on the computer changes.
- The Windows launcher checks the download's SHA-256 fingerprint before using it.
- If the download is blocked, the launchers fall back to an installed Python, as before.
- Moving the hub's folder no longer breaks it — the launcher notices and rebuilds in seconds.
- The menu installs each tool's libraries with uv, which is several times faster.
- A new automated check runs every launcher from a fresh copy on Windows, macOS and Linux, exactly like a new user.

### Updated
- Library updates: pandas 3 (Python 3.11+), pytest 9.2, openpyxl 3.1.5, faster-whisper 1.2.1, and newer GitHub Actions.
- Dependabot now only proposes updates that fall outside the allowed versions, and skips versions known to break the hub (Pillow 13 while Python 3.10 is supported; av 16+).

## [1.0.0] — 2026-11-05

The first full release: 13 tools, a double-click menu, and a test suite that runs on Windows, macOS and Linux.

### Start here
- **"Start here" menu** (`start.py`) with double-click launchers for Windows, Mac and Linux. It installs each tool's libraries on first use, opens the right folder, runs the tool, and offers to open the results.

### Tools
- **Image Compressor & Converter** — JPG/PNG to `.webp` under ~200 KB; shrinks very large photos when needed; keeps colours and transparency.
- **Background Remover** — offline background removal with transparent or white backgrounds.
- **PDF Text & Image Extractor** — text by page plus every embedded picture, with duplicate logos skipped.
- **Scanned Document Reader (OCR)** — reads scanned PDFs, photos of documents and screenshots, in reading order.
- **Mail-Merge Certificates & Letters** — Word template + spreadsheet → personalised Word files and PDFs.
- **Spreadsheet Cleaner** — removes duplicate rows and standardizes dates, keeping IDs, `N/A` and every sheet intact.
- **Spreadsheet Merger** — combines many Excel/CSV files, matching columns even when names differ slightly.
- **Audio-to-Text Transcriber** — private, offline transcripts with timestamps and a plain-text version.
- **Video Subtitle Maker** — readable `.srt` and `.vtt` subtitles.
- **Meeting Notes Summarizer** — summary, decisions and action items using a local AI model via Ollama.
- **Bulk File Renamer** — tidy numbered names with preview and undo.
- **Duplicate File Finder** — finds exact copies and similar photos; moves extras aside, never deletes, with undo.
- **Website-to-Markdown Scraper** — clean article text without ads, menus and pop-ups.

### Project
- 351 automated tests, run on every push for Python 3.10 and 3.13 on Windows, macOS and Linux.
- A guide for every tool, with screenshots and demo GIFs made from real runs.
- Issue forms for tool ideas and bug reports, a contributing guide, Code of Conduct, Security policy and Dependabot.

[1.1.0]: https://github.com/kapoorraghav-cmd/niche-automation-script-hub/releases/tag/v1.1.0
[1.0.0]: https://github.com/kapoorraghav-cmd/niche-automation-script-hub/releases/tag/v1.0.0

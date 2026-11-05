# Changelog

All notable changes to this project are listed here.

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

[1.0.0]: https://github.com/kapoorraghav-cmd/niche-automation-script-hub/releases/tag/v1.0.0

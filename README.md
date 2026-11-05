# Niche Automation Script Hub

[![Tests](https://github.com/kapoorraghav-cmd/niche-automation-script-hub/actions/workflows/tests.yml/badge.svg)](https://github.com/kapoorraghav-cmd/niche-automation-script-hub/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Simple Python scripts that automate tedious office tasks — written for non-technical people.**

No dashboards. No accounts. Each tool is one script you drop files into and run from your terminal.

---

## Table of contents

1. [Why this hub exists](#1-why-this-hub-exists)
2. [Active scripts (start here)](#2-active-scripts-start-here)
3. [Quick start](#3-quick-start)
4. [Complete beginner setup](#4-complete-beginner-setup)
5. [Tool guides](#5-tool-guides)
   - [Image Compressor & Converter](#51-image-compressor--converter)
   - [Spreadsheet Cleaner](#52-spreadsheet-cleaner)
6. [Project folder layout](#6-project-folder-layout)
7. [Safe tips for non-developers](#7-safe-tips-for-non-developers)
8. [Troubleshooting](#8-troubleshooting)
9. [Contributing](#9-contributing)
10. [License](#10-license)

---

## 1. Why this hub exists

Office work is full of repetitive chores: shrinking photo attachments, cleaning messy spreadsheets, renaming files. This repository collects **small, separate scripts** so you can:

- Use only the tool you need
- Read the code (it is heavily commented on purpose)
- Trust that your originals are never overwritten

If you have never used Python before, start at [Complete beginner setup](#4-complete-beginner-setup).

---

## 2. Active scripts (start here)

| # | Tool | Script file | Input folder | Output folder | What it does |
|---|------|-------------|--------------|---------------|--------------|
| 1 | **Image Compressor & Converter** | [`image_compressor.py`](image_compressor.py) | `input_images/` | `optimized_images/` | Compresses JPG/PNG (aims for under ~200 KB) and converts them to modern `.webp` |
| 2 | **Spreadsheet Cleaner** | [`excel_cleaner.py`](excel_cleaner.py) | `input_spreadsheets/` | `cleaned_spreadsheets/` | Removes completely duplicate rows, standardizes dates to `YYYY-MM-DD`, saves a `*_cleaned` copy |

Jump to the full how-to for each tool:

- [→ Image Compressor & Converter guide](#51-image-compressor--converter)
- [→ Spreadsheet Cleaner guide](#52-spreadsheet-cleaner)

---

## 3. Quick start

Already comfortable with Python? Do this from the project folder:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows CMD: .venv\Scripts\activate
pip install -r requirements.txt
```

Then run whichever tool you need:

```bash
python image_compressor.py         # after putting photos in input_images/
python excel_cleaner.py            # after putting Excel/CSV in input_spreadsheets/
```

New to all of this? Keep reading — the next section walks through every click.

---

## 4. Complete beginner setup

Follow the section for **your** computer. Take your time — each step is written for someone who has never used Python.

### Step A — Install Python

#### On Windows

1. Open your web browser and go to: [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. Click the big yellow **Download Python** button.
3. Run the installer you just downloaded.
4. **IMPORTANT:** On the first screen, check the box that says **"Add python.exe to PATH"** (near the bottom).
5. Click **Install Now** and wait until it finishes.
6. Close the installer.

#### On Mac

**Option 1 (easiest for many people):**

1. Go to [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. Download the latest macOS installer.
3. Open the `.pkg` file and click through **Continue / Install**.
4. When it finishes, you’re done with this step.

**Option 2 (if you already use Homebrew):**

```bash
brew install python
```

#### On Linux (Ubuntu / Debian-style)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### Step B — Confirm Python works

1. Open a terminal:
   - **Windows:** Press the Windows key, type `cmd` or `PowerShell`, and press Enter.
   - **Mac:** Press `Command + Space`, type `Terminal`, press Enter.
   - **Linux:** Open your Terminal app.
2. Type one of these and press Enter:

```bash
python --version
```

If that fails on Mac/Linux, try:

```bash
python3 --version
```

You should see something like `Python 3.12.x` (any 3.10+ is fine).

> **Note:** If `python` does not work but `python3` does, use `python3` and `pip3` everywhere below instead of `python` and `pip`.

### Step C — Get this project onto your computer

**If you downloaded a ZIP from GitHub:**

1. Unzip the file.
2. Put the folder somewhere easy to find (for example your Desktop).

**If you use Git:**

```bash
git clone https://github.com/YOUR-USERNAME/niche-automation-script-hub.git
cd niche-automation-script-hub
```

(Replace the URL with your real repository link after you publish.)

### Step D — Open the terminal inside the project folder

#### Windows (Command Prompt)

```bash
cd Desktop\"Niche Automation Script Hub"
```

#### Mac / Linux

```bash
cd ~/Desktop/"Niche Automation Script Hub"
```

Check you’re in the right place (`ls` on Mac/Linux, `dir` on Windows). You should see `image_compressor.py`, `excel_cleaner.py`, `requirements.txt`, and `README.md`.

### Step E — Create a virtual environment (recommended)

A virtual environment is a **private toolbox** for this project.

```bash
python -m venv .venv
```

Activate it:

| System | Command |
|--------|---------|
| Windows Command Prompt | `.venv\Scripts\activate` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Mac / Linux | `source .venv/bin/activate` |

If PowerShell blocks activation:

```bash
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

You should see `(.venv)` at the start of your terminal line when it worked.

### Step F — Install the required libraries

```bash
pip install -r requirements.txt
```

Fallbacks if needed:

```bash
python -m pip install -r requirements.txt
# or
pip3 install -r requirements.txt
```

| Library | Used by | Why you need it |
|---------|---------|-----------------|
| **Pillow** | Image Compressor | Opens, compresses, and saves images |
| **pandas** | Spreadsheet Cleaner | Reads tables; removes duplicates; fixes dates |
| **openpyxl** | Spreadsheet Cleaner | Reads/writes modern Excel `.xlsx` files |
| **xlrd** | Spreadsheet Cleaner | Reads older Excel `.xls` files |

Only need one tool?

```bash
pip install Pillow                 # images only
pip install pandas openpyxl xlrd   # spreadsheets only
```

Using `pip install -r requirements.txt` is the safest choice so every tool works.

---

## 5. Tool guides

### 5.1 Image Compressor & Converter

**Script:** [`image_compressor.py`](image_compressor.py)

#### 1. Put your photos in the input folder

Create (or let the script create) a folder named exactly `input_images` next to the script. Copy `.jpg`, `.jpeg`, or `.png` files **directly** into it (no subfolders, no HEIC/PDF).

#### 2. Run the script

```bash
python image_compressor.py
```

#### 3. Watch the progress

```text
Compressing image 1 of 5: vacation.jpg ...
   Done! 4.2 MB → 187.6 KB (WebP quality 72)
   Resized from 4032 × 3024 to 2105 × 1579 pixels to fit under 200 KB.
   Saved as: vacation.webp — under 200 KB ✓
```

#### 4. Get your finished files

Open `optimized_images/`. Every finished picture is a `.webp` file — smaller and still looking good for email, websites, and most office work.

**Your originals in `input_images/` are never changed.**

#### How it keeps pictures looking good

1. It first lowers the WebP quality, but never below 60 (below that, photos start to look smudgy).
2. Full-size phone photos (12 megapixels and up) can't reach 200 KB that way, so the tool then shrinks the width and height a little at a time. It never goes below 1280 pixels on the longest side, which still looks sharp on screens and in documents.
3. If a picture still can't reach 200 KB (very detailed images sometimes can't), it keeps the best-looking small version and tells you.

It also turns sideways phone photos the right way up, keeps transparent PNG backgrounds transparent, and keeps the original colors. Phone location (GPS) data is **not** copied into the new file.

---

### 5.2 Spreadsheet Cleaner

**Script:** [`excel_cleaner.py`](excel_cleaner.py)

#### 1. Put your spreadsheets in the input folder

Use the folder `input_spreadsheets/`. Supported types:

- `.xlsx` (modern Excel — recommended)
- `.xls` (older Excel — cleaned copy is saved as `.xlsx`)
- `.csv`

#### 2. Run the script

```bash
python excel_cleaner.py
```

#### 3. What it does

1. Removes **completely duplicate rows** (every column matches).
2. Standardizes date-like columns to **`YYYY-MM-DD`** (example: `2024-03-15`).
3. Saves a new file with `_cleaned` in the name. Originals are never overwritten.

Everything else is kept exactly as you typed it:

- ID numbers keep their leading zeros (`00123` stays `00123`).
- Text like `N/A`, `null`, or `TBD` stays as typed instead of becoming blank.
- Years, hours, and times of day (`2024`, `8.5`, `09:30`) are not mistaken for dates.
- Every sheet in an Excel workbook is cleaned and kept, with the same sheet names.
- CSV files saved by Excel on Windows (with `£` or `é` in them) open correctly.

```text
Cleaning file 1 of 2: sales.xlsx ...
   Loaded 120 row(s) and 6 column(s).
   Removing completely duplicate rows...
   Removed 8 duplicate row(s). 112 row(s) remain.
   Checking for inconsistent date formats...
   Standardized dates in: Order Date, Ship Date
   Done! Saved as: sales_cleaned.xlsx
```

#### 4. Get your cleaned files

Open `cleaned_spreadsheets/`:

| You put this in `input_spreadsheets` | You get this in `cleaned_spreadsheets` |
|--------------------------------------|----------------------------------------|
| `sales.xlsx` | `sales_cleaned.xlsx` |
| `contacts.csv` | `contacts_cleaned.csv` |
| `legacy.xls` | `legacy_cleaned.xlsx` |

#### Date format notes

- Output dates look like **`2024-03-15`** (year-month-day). If a column also has times, they are kept: `2024-03-15 14:30`.
- A value only counts as a date if it shows a year (like `2024` inside `15 Mar 2024`, or a short date like `15/03/24`).
- Columns named things like `Date`, `Order Date`, `DOB`, or `Deadline` are cleaned when at least half their values are dates.
- Other columns change only if almost all values clearly look like dates (so invoice numbers stay numbers).
- Values in a date column that aren't dates (like `TBD`) are left as they are.
- In Excel files, cleaned dates are saved as text so they always show as `YYYY-MM-DD`.
- Ambiguous values like `01/02/2024` are read as **month/day/year** (US style). If your office uses day/month/year, spot-check a few rows.

---

## 6. Project folder layout

```text
Niche Automation Script Hub/
├── README.md                  ← you are here (hub landing page)
├── requirements.txt           ← Python packages to install
├── requirements-dev.txt       ← extra packages for running the tests
├── .gitignore                 ← keeps junk / user data off GitHub
├── LICENSE                    ← MIT license
├── image_compressor.py        ← Tool 1
├── excel_cleaner.py           ← Tool 2
├── tests/                     ← automated checks for every tool
├── .github/workflows/         ← runs the tests on GitHub after every change
├── input_images/              ← drop original JPG/PNG here
├── optimized_images/          ← finished .webp files appear here
├── input_spreadsheets/        ← drop original Excel/CSV here
└── cleaned_spreadsheets/      ← finished *_cleaned files appear here
```

Empty input/output folders are kept in Git with tiny `.gitkeep` files. Your real photos and spreadsheets stay on your computer only (see `.gitignore`).

---

## 7. Safe tips for non-developers

- **Originals stay untouched.** Tools write only to `optimized_images/` or `cleaned_spreadsheets/`.
- **Keep a backup** of important files before batch-processing anything.
- **Close Excel** on a file before cleaning it — locked files can fail to save.
- **Stop anytime** with `Ctrl + C` in the terminal.
- **Don’t paste random commands** from strangers. Only use commands from this README (or people you trust).
- **Stay in the project folder** before running `pip install` or a script.

---

## 8. Troubleshooting

| Problem | What to try |
|---------|-------------|
| `'python' is not recognized` | Reinstall Python and check **Add to PATH**. Or try `python3`. Open a **new** terminal after installing. |
| `No module named 'PIL'` | `pip install Pillow` or `pip install -r requirements.txt` |
| `No module named 'pandas'` | `pip install pandas openpyxl xlrd` or `pip install -r requirements.txt` |
| Error mentioning `openpyxl` | `pip install openpyxl` |
| Error mentioning `xlrd` (old `.xls` files) | `pip install xlrd` |
| No images found | Put `.jpg` / `.png` **directly** into `input_images/` |
| No Excel/CSV found | Put `.xlsx` / `.xls` / `.csv` **directly** into `input_spreadsheets/` |
| Image still over 200 KB | Very detailed pictures sometimes can’t reach 200 KB without looking bad; the tool keeps the best-looking small version |
| Dates look wrong (day/month swapped) | Source may use day-first dates — spot-check and fix those columns in Excel if needed |
| PowerShell won’t activate `.venv` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` then activate again |
| Permission / “access denied” | Close the file in Excel/Preview, then try again |

---

## 9. Contributing

This hub is open source and meant to stay **simple**:

- One script ≈ one clear job
- Heavy comments for beginners
- Friendly terminal messages
- No complicated frameworks unless truly needed
- Every tool comes with automated tests

### Running the tests

The tests create sample photos and spreadsheets in a temporary folder, run each tool on them, and check the results. They never touch your own files.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

You should see a line like `28 passed`. The same tests run automatically on GitHub (Windows, Mac, and Linux) every time a change is pushed — that's what the green **Tests** badge at the top of this page shows.

Ideas welcome: PDF renaming, email attachment sorting, file organizers, and more. Open an issue or pull request on GitHub.

---

## 10. License

Released under the [MIT License](LICENSE). You are free to use, copy, modify, and share these scripts, including for commercial work, as long as the license notice stays with them.

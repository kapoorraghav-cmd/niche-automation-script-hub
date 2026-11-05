#!/usr/bin/env python3
"""
Meeting Notes Summarizer
========================
This script reads meeting transcripts and writes tidy meeting notes for each
one: a short summary, the key decisions, a table of action items (what needs
doing, who will do it, and by when) and the questions that are still open.

It is the natural next step after the Audio-to-Text Transcriber: by default it
reads the "transcripts" folder that the transcriber fills. You can also drop
your own .txt or .md meeting notes or transcripts into that folder.
The finished notes are saved as Markdown (.md) files in "meeting_notes".

The notes are written by an AI model that runs on YOUR computer, using the
free Ollama app (https://ollama.com). Nothing is uploaded to the internet, so
private meetings stay private. The model is downloaded once (the first time
you run the script); after that it works fully offline.

AI models make mistakes. Always check the notes against the transcript before
you share them. Your transcripts are never changed.

How to run (after following README.md and installing Ollama):
    python meeting_summarizer.py
"""

# ---------------------------------------------------------------------------
# Imports — all built into Python, nothing extra to install
# ---------------------------------------------------------------------------

import http.client  # Lets us recognise "the connection dropped" errors
import json  # The text format Ollama uses to send and receive messages
import math  # Rounds numbers up when splitting long meetings into parts
import os  # Reads optional settings from the environment (see below)
import re  # "Regular expressions" — used to find timestamps like [00:01:23]
import shutil  # Checks whether the Ollama program is installed
import socket  # Lets us recognise timeout errors
import sys  # Gives access to the terminal output settings
import time  # Measures how long each meeting took
import urllib.error  # The errors the built-in web tools can raise
import urllib.request  # Python's built-in tool for talking to Ollama
from datetime import datetime  # Puts today's date in each notes file
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import Optional


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder the script reads from. This is where the Audio-to-Text Transcriber
# saves its transcripts, so the two tools work together without any setup.
INPUT_FOLDER_NAME = "transcripts"

# Folder where THIS SCRIPT saves the finished notes
OUTPUT_FOLDER_NAME = "meeting_notes"

# Which AI model writes the notes. Bigger = better notes but slower, and a
# bigger one-time download. It also needs that much free memory (RAM) to run.
#   "llama3.2:1b" — ~1.3 GB download. Fastest; fine for short, simple
#                   meetings, but misses more details.
#   "llama3.2:3b" — ~2.0 GB download. Good everyday balance (the default).
#                   Works on most laptops with 8 GB of memory.
#   "qwen2.5:7b"  — ~4.7 GB download. Noticeably better notes, about 2 to 3
#                   times slower. Best with 16 GB of memory.
# Any other model from https://ollama.com/library works too.
# (Advanced: you can also choose a model for a single run without editing this
# file by setting the MEETING_SUMMARIZER_MODEL environment variable.)
MODEL = os.environ.get("MEETING_SUMMARIZER_MODEL", "llama3.2:3b")

# Approximate download sizes, shown on the first run so the wait makes sense
MODEL_DOWNLOAD_SIZES = {
    "llama3.2:1b": "1.3 GB",
    "llama3.2:3b": "2.0 GB",
    "llama3.2": "2.0 GB",
    "qwen2.5:7b": "4.7 GB",
}

# Where the Ollama app listens. This address means "this computer", so your
# transcripts never leave it. Only change it if you run Ollama somewhere else.
# (Advanced: the MEETING_SUMMARIZER_OLLAMA_URL environment variable overrides it.)
OLLAMA_URL = os.environ.get("MEETING_SUMMARIZER_OLLAMA_URL", "http://localhost:11434")

# How "creative" the model may be, from 0 to 1. Low values keep the notes
# close to what was actually said, which is what we want for meeting notes.
TEMPERATURE = 0.2

# How much text the model can look at in one go (measured in "tokens";
# one word is roughly 1.3 tokens). 8192 fits a 3,000-word part of a meeting
# plus our instructions and the notes it writes back.
CONTEXT_TOKENS = 8192

# Long meetings are split into parts of at most this many words. Each part is
# summarised on its own, then the parts are combined into one set of notes.
CHUNK_WORDS = 3000

# How long to wait for the model to write the notes for one part (in seconds).
# Older laptops can be slow, so this is generous: 10 minutes.
REQUEST_TIMEOUT_SECONDS = 600

# How long to wait when simply checking that Ollama is running (in seconds)
CONNECT_TIMEOUT_SECONDS = 5

# Files with fewer words than this are too short to make notes from
MIN_WORDS = 15

# Print a download progress line every time this much more is done
PROGRESS_EVERY_PERCENT = 10

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".txt", ".md"}

# What we write when the transcript doesn't name an owner or a due date
NOT_MENTIONED = "not mentioned"

# Answers models sometimes give instead of "not mentioned" — we tidy them up
EMPTY_ANSWERS = {
    "", "-", "—", "none", "null", "n/a", "na", "unknown", "unassigned", "nobody",
    "not mentioned", "not specified", "not stated", "not given", "not provided",
}

# Owners that aren't really names ("I'll take care of it", "we", "someone").
# Only English words are listed; other languages keep whatever the model wrote.
NOT_A_NAME = re.compile(
    r"^(i|me|myself|we|us|you|they|them|someone|somebody|anyone|speaker)\b", re.IGNORECASE
)

# A timestamp at the start of a line, like the transcriber's "[00:01:23] "
TIMESTAMP = re.compile(r"^\s*\[\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\]\s*")

# The header lines and section titles the Audio-to-Text Transcriber writes
TRANSCRIBER_HEADER_LINE = re.compile(
    r"^(Transcript of|Length|Language|Speech model|Created on):", re.IGNORECASE
)
TRANSCRIBER_SECTION_TITLE = re.compile(r"^(WITH TIMESTAMPS|PLAIN TEXT)\b")
DIVIDER_LINE = re.compile(r"^\s*-{10,}\s*$")

# The exact shape of the answer we want back from the model (a "JSON schema").
# Ollama uses it to make the model reply in this structure, which makes the
# answer far more reliable to read than free-form text.
NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                },
                "required": ["action", "owner", "due"],
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "decisions", "action_items", "open_questions"],
}

# The instructions the model gets for every transcript (or part of one).
# AI models like to "fill in the blanks". A made-up owner or deadline in an
# action item can cause real trouble at work, so the instructions insist on
# writing "not mentioned" instead of guessing.
SUMMARY_INSTRUCTIONS = """\
You turn meeting transcripts into clear, accurate meeting notes.
Use ONLY what is said in the transcript. Never guess, and never add anything that was not said.
The transcript has no speaker labels, so you often cannot tell who is speaking.

Reply with JSON containing these fields:
- "summary": 2 to 4 sentences saying what the meeting was about and what came out of it.
- "decisions": things the group clearly agreed or decided. Leave out ideas that were only suggested.
- "action_items": every task someone agreed to do after the meeting. For each task:
    - "action": a short description of the task from the transcript, starting with a verb.
    - "owner": the first name of the person who will do the task, only if the transcript
      clearly names them for that task. If the task has no name (for example the speaker
      only says "I'll do it"), write exactly "not mentioned". Never write a pronoun here.
    - "due": the deadline for the task, in the words used in the meeting.
      If no deadline is given for that task, write exactly "not mentioned".
- "open_questions": questions or problems that were raised but NOT answered or settled.

Use an empty list when a field has nothing in it.
Write the notes in the same language as the transcript."""

COMBINE_INSTRUCTIONS = """\
You combine partial notes from one long meeting into a single final set of notes.
The partial notes come from consecutive parts of the same meeting, in order.
Use ONLY the information in the partial notes. Never add anything new.

Reply with JSON containing these fields:
- "summary": 3 to 5 sentences covering the whole meeting.
- "decisions": every decision from all parts.
- "action_items": every action item from all parts, keeping "owner" and "due" exactly as written.
- "open_questions": every open question, except ones that a later part answered or decided.

Keep every item. Only merge two items when they clearly describe the same thing.
Write in the same language as the partial notes."""

# What we say if the model's first answer wasn't in the right format
RETRY_INSTRUCTIONS = (
    "Your reply was not valid JSON in the requested format. Reply again with ONLY "
    'the JSON object with the fields "summary", "decisions", "action_items" and '
    '"open_questions". No other text.'
)

# Ollama runs on this computer, so we always connect to it directly and never
# through a "proxy" (an in-between server some office networks use for websites).
DIRECT_CONNECTION = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class FriendlyError(Exception):
    """A problem we can explain in plain English, so we skip the file politely."""


def format_length(seconds: float) -> str:
    """Turn a number of seconds into friendly text like '3 min 12 sec'."""
    if seconds < 10:
        return f"{seconds:.1f} sec"
    seconds = round(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes} min {secs} sec" if secs else f"{minutes} min"
    return f"{secs} sec"


def print_problem_box(lines: list[str]) -> None:
    """Print an important message inside a box of '=' signs so it stands out."""
    print()
    print("=" * 60)
    for line in lines:
        print(line)
    print("=" * 60)
    print()


def ensure_folders() -> tuple[Path, Path]:
    """
    Make sure the input and output folders exist.
    Returns (input_path, output_path).
    """
    # Path(".") means "the folder where you ran the script from"
    project_root = Path(".")

    input_dir = project_root / INPUT_FOLDER_NAME
    output_dir = project_root / OUTPUT_FOLDER_NAME

    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {input_dir.resolve()}")
        print("   → Put your meeting transcripts (.txt or .md) in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_transcripts(input_dir: Path) -> list[Path]:
    """Return a sorted list of .txt and .md files in the input folder (not subfolders)."""
    transcripts = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._notes.txt"
        # copies macOS leaves on USB drives — they are not real transcripts.
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            transcripts.append(item)

    # Sort alphabetically so "file 1 of 5" feels predictable
    return sorted(transcripts, key=lambda p: p.name.lower())


def clean_transcript(raw: str) -> tuple[str, str]:
    """
    Get the spoken words out of a file, ready to send to the model.
    Returns (text, what_we_did) where what_we_did is one of:
      "transcriber" — a file from the Audio-to-Text Transcriber; we used its
                      plain-text part (the same words, without timestamps)
      "timestamps"  — timestamps like [00:01:23] were removed
      "plain"       — the file was used as it is
    """
    lines = raw.splitlines()
    from_transcriber = bool(lines) and lines[0].startswith("Transcript of:")

    if from_transcriber:
        # The transcriber writes everything twice: first with timestamps, then
        # as plain paragraphs under a "PLAIN TEXT" title. The plain part is
        # exactly what we need, so we use it when it's there.
        for position, line in enumerate(lines):
            if TRANSCRIBER_SECTION_TITLE.match(line) and line.startswith("PLAIN TEXT"):
                plain = [text for text in lines[position + 1:] if not DIVIDER_LINE.match(text)]
                text = "\n".join(plain).strip()
                if text:
                    return text, "transcriber"
                break

    # Otherwise keep every line, minus the transcriber's header lines and
    # dividers (if any) and the timestamps at the start of lines
    kept = []
    removed_timestamps = False
    for line in lines:
        if from_transcriber and (
            TRANSCRIBER_HEADER_LINE.match(line)
            or TRANSCRIBER_SECTION_TITLE.match(line)
            or DIVIDER_LINE.match(line)
        ):
            continue
        without_timestamp = TIMESTAMP.sub("", line)
        if without_timestamp != line:
            removed_timestamps = True
        kept.append(without_timestamp.rstrip())

    # Squeeze runs of blank lines down to one blank line
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if from_transcriber:
        return text, "transcriber"
    return text, "timestamps" if removed_timestamps else "plain"


def split_into_chunks(text: str, max_words: int) -> list[str]:
    """
    Split a long transcript into parts of at most max_words words each, so
    every part fits in what the model can read at once.

    We cut between lines (and, for very long lines, between sentences) so no
    sentence is chopped in half. The parts are kept roughly equal in size:
    a 3,300-word meeting becomes two parts of ~1,650 words, not 3,000 + 300.
    """
    pieces: list[str] = []
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if len(words) <= max_words:
            pieces.append(line.strip())
            continue
        # A huge paragraph: cut it into sentences (and only as a last resort,
        # cut a gigantic "sentence" with no full stops into word groups)
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            sentence_words = sentence.split()
            for start in range(0, len(sentence_words), max_words):
                pieces.append(" ".join(sentence_words[start:start + max_words]))

    total_words = sum(len(piece.split()) for piece in pieces)
    if total_words <= max_words:
        return ["\n".join(pieces)] if pieces else []

    target = total_words / math.ceil(total_words / max_words)
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for piece in pieces:
        piece_words = len(piece.split())
        if current and (current_words + piece_words > max_words or current_words >= target):
            chunks.append("\n".join(current))
            current, current_words = [], 0
        current.append(piece)
        current_words += piece_words
    if current:
        chunks.append("\n".join(current))
    return chunks


def ollama_address() -> str:
    """The Ollama address without a "/" at the end, e.g. http://localhost:11434"""
    return OLLAMA_URL.rstrip("/")


def open_ollama(path: str, payload: Optional[dict], timeout: float):
    """Send one request to Ollama (GET if there is no payload, else POST)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_address() + path, data=data, headers={"Content-Type": "application/json"}
    )
    return DIRECT_CONNECTION.open(request, timeout=timeout)


def ollama_error_text(err: urllib.error.HTTPError) -> str:
    """Ollama explains its errors in a small JSON message — read it if we can."""
    try:
        return json.loads(err.read().decode("utf-8", errors="replace")).get("error") or str(err)
    except Exception:
        return str(err)


def ollama_seems_installed() -> bool:
    """True if the Ollama program can be found on this computer."""
    if shutil.which("ollama"):
        return True
    usual_places = [Path("/Applications/Ollama.app")]  # macOS
    if os.environ.get("LOCALAPPDATA"):  # Windows
        usual_places.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama" / "ollama.exe")
    return any(place.exists() for place in usual_places)


def explain_ollama_not_reachable() -> list[str]:
    """The message we show when nothing answers at the Ollama address."""
    if ollama_seems_installed():
        return [
            "Oops! Ollama is installed, but it isn't running right now.",
            "This tool needs the Ollama app open to write your notes.",
            "",
            "What to do:",
            "  1. Open the Ollama app (Start menu on Windows,",
            "     Applications folder on Mac). On Linux, or if there",
            "     is no app, open a new terminal and run:  ollama serve",
            "  2. Wait a few seconds, then run this script again:",
            "",
            "         python meeting_summarizer.py",
            "",
            f"(This script looked for Ollama at {ollama_address()})",
        ]
    return [
        "Oops! Ollama isn't installed on this computer yet.",
        "Ollama is a free app that runs AI models on your own",
        "computer, so your meetings are never uploaded anywhere.",
        "",
        "One-time setup:",
        "  1. Download and install Ollama from https://ollama.com",
        "  2. Open the Ollama app (on Linux, run:  ollama serve)",
        "  3. Run this script again:",
        "",
        "         python meeting_summarizer.py",
        "",
        "See docs/tools/meeting-summarizer.md for step-by-step help.",
    ]


def list_downloaded_models() -> list[str]:
    """
    Check that Ollama is running and return the names of the models it has.
    Stops the script with clear steps if Ollama can't be reached.
    """
    try:
        with open_ollama("/api/tags", None, CONNECT_TIMEOUT_SECONDS) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        print_problem_box([
            f"Oops! Something answered at {ollama_address()},",
            "but it doesn't seem to be Ollama.",
            "Check the OLLAMA_URL setting at the top of meeting_summarizer.py",
            "(the usual value is http://localhost:11434).",
            "",
            f"Technical details: {ollama_error_text(err)}",
        ])
        raise SystemExit(1)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
            http.client.HTTPException, ValueError):
        print_problem_box(explain_ollama_not_reachable())
        raise SystemExit(1)

    return [model.get("name", "") for model in reply.get("models", [])]


def same_model(name_a: str, name_b: str) -> bool:
    """'llama3.2' and 'llama3.2:latest' are the same model to Ollama."""
    def full_name(name: str) -> str:
        return name if ":" in name else f"{name}:latest"
    return full_name(name_a.strip().lower()) == full_name(name_b.strip().lower())


def download_model() -> None:
    """Ask Ollama to download the model, printing a progress line as it goes."""
    download_size = MODEL_DOWNLOAD_SIZES.get(MODEL, "a few GB")
    print(f"   First run: downloading the '{MODEL}' AI model (about {download_size}).")
    print("   This happens only once and can take a while on slow internet.")
    print("   Only the model is downloaded — your transcripts are NOT uploaded.")
    print("   After this, writing notes works fully offline.")

    # Ollama sends a stream of small progress messages while it downloads.
    # A model comes in a few pieces; we add them all up for one overall number.
    totals: dict[str, int] = {}
    done: dict[str, int] = {}
    next_report = PROGRESS_EVERY_PERCENT
    problem = None

    try:
        with open_ollama("/api/pull", {"model": MODEL, "stream": True}, 120) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                message = json.loads(raw_line.decode("utf-8"))
                if message.get("error"):
                    problem = message["error"]
                    break
                piece = message.get("digest")
                if piece and message.get("total"):
                    totals[piece] = message["total"]
                    done[piece] = message.get("completed", 0)
                    percent = int(sum(done.values()) / sum(totals.values()) * 100)
                    if percent >= next_report:
                        gigabytes = 1024 ** 3
                        print(
                            f"   Downloading... {percent}% "
                            f"({sum(done.values()) / gigabytes:.1f} of "
                            f"{sum(totals.values()) / gigabytes:.1f} GB)",
                            flush=True,  # Show the line now, not when the script ends
                        )
                        # Jump to the next round number, e.g. from 37% to the 40% mark
                        next_report = (percent // PROGRESS_EVERY_PERCENT + 1) * PROGRESS_EVERY_PERCENT
                if message.get("status") == "success":
                    break
            else:
                problem = "the download stopped before it was finished"
    except urllib.error.HTTPError as err:
        problem = ollama_error_text(err)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
            http.client.HTTPException, ValueError) as err:
        problem = f"the connection dropped ({err})"

    if problem:
        if "file does not exist" in problem or "not found" in problem:
            hint = [
                f"'{MODEL}' doesn't seem to be a model name Ollama knows.",
                "Open meeting_summarizer.py and set MODEL to one of:",
                "",
                '    "llama3.2:1b", "llama3.2:3b", or "qwen2.5:7b"',
                "",
                'If you are not sure, use "llama3.2:3b".',
            ]
        else:
            hint = [
                "What to try:",
                "  1. Check your internet connection (the first run needs it).",
                "  2. Make sure you have enough free disk space",
                f"     (the model needs about {download_size}).",
                "  3. Run this script again — the download continues where",
                "     it stopped. Your transcripts were not changed.",
            ]
        print_problem_box(
            ["Oops! The AI model could not be downloaded.", ""] + hint
            + ["", f"Technical details: {problem}"]
        )
        raise SystemExit(1)

    print("   Ready! Model downloaded and saved for next time.")


def prepare_model() -> None:
    """Make sure Ollama is running and the model is on this computer."""
    print("Connecting to Ollama (the free app that runs the AI model on this computer)...")
    models = list_downloaded_models()
    if any(same_model(name, MODEL) for name in models):
        print(f"   Ready! Using the '{MODEL}' model (no internet needed).")
    else:
        download_model()
    print()


def explain_ollama_problem(text: str) -> str:
    """Turn an error message from Ollama into a sentence a non-developer can act on."""
    lowered = text.lower()
    if "memory" in lowered:
        return (
            f"your computer doesn't have enough free memory for the '{MODEL}' model. "
            "Close other apps and try again, or set MODEL to \"llama3.2:1b\" "
            "(a smaller model) at the top of meeting_summarizer.py."
        )
    if "format" in lowered:
        return (
            "your Ollama app is too old for this tool. Update it from "
            "https://ollama.com and run this script again."
        )
    return f"Ollama reported a problem: {text}"


def ask_model(messages: list[dict]) -> str:
    """Send a conversation to the model and return the text it writes back."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,  # Wait for the whole answer instead of word by word
        "format": NOTES_SCHEMA,  # Make the answer follow our JSON structure
        "options": {"temperature": TEMPERATURE, "num_ctx": CONTEXT_TOKENS},
    }
    too_slow = (
        f"the AI model took longer than {format_length(REQUEST_TIMEOUT_SECONDS)} to answer. "
        "Try again with fewer apps open, or set MODEL to \"llama3.2:1b\" "
        "(faster) at the top of meeting_summarizer.py."
    )
    try:
        with open_ollama("/api/chat", payload, REQUEST_TIMEOUT_SECONDS) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise FriendlyError(explain_ollama_problem(ollama_error_text(err))) from err
    except urllib.error.URLError as err:
        if isinstance(err.reason, (socket.timeout, TimeoutError)):
            raise FriendlyError(too_slow) from err
        raise FriendlyError(
            "lost the connection to Ollama. Make sure the Ollama app is still open, then run again."
        ) from err
    except (socket.timeout, TimeoutError) as err:
        raise FriendlyError(too_slow) from err
    except (http.client.HTTPException, ConnectionError, ValueError) as err:
        raise FriendlyError(
            "the connection to Ollama dropped. Make sure the Ollama app is still open, then run again."
        ) from err

    return (reply.get("message") or {}).get("content") or ""


def tidy_text(value) -> str:
    """Turn whatever the model gave us into one clean line of text."""
    if isinstance(value, dict):
        value = " — ".join(str(part) for part in value.values() if part)
    elif isinstance(value, list):
        value = " ".join(str(part) for part in value if part)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def capitalise(text: str) -> str:
    """Start with a capital letter ('book the room' → 'Book the room'), but leave 'iPhone' alone."""
    if text[1:2].isupper():
        return text
    return text[:1].upper() + text[1:]


def tidy_list(value) -> list[str]:
    """A clean list of non-empty lines (models sometimes write 'None' as an item)."""
    if not isinstance(value, list):
        value = [value] if value else []
    items = [capitalise(tidy_text(item)) for item in value]
    return [item for item in items if item.lower().strip(".") not in EMPTY_ANSWERS]


def tidy_detail(value) -> str:
    """An owner or due date, or 'not mentioned' if the model left it blank or vague."""
    text = tidy_text(value)
    return NOT_MENTIONED if text.lower().strip(".") in EMPTY_ANSWERS else text


def parse_notes(reply: str) -> Optional[dict]:
    """
    Read the model's answer as notes. Returns None if it isn't usable JSON.

    The notes always come back in the same shape:
      {"summary": "...", "decisions": [...], "open_questions": [...],
       "action_items": [{"action": "...", "owner": "...", "due": "..."}, ...]}
    """
    text = reply.strip()
    # Some models wrap their JSON in ```json ... ``` marks — remove them
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        # Maybe there's a sentence before or after the JSON — try just the {...} part
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return None

    expected = ("summary", "decisions", "action_items", "open_questions")
    if not isinstance(data, dict) or not any(key in data for key in expected):
        return None

    actions = []
    raw_actions = data.get("action_items")
    for item in raw_actions if isinstance(raw_actions, list) else []:
        if isinstance(item, dict):
            action = capitalise(tidy_text(item.get("action") or item.get("task")))
            owner, due = tidy_detail(item.get("owner")), tidy_detail(item.get("due"))
            if NOT_A_NAME.match(owner):
                owner = NOT_MENTIONED
        else:
            action, owner, due = capitalise(tidy_text(item)), NOT_MENTIONED, NOT_MENTIONED
        if action and action.lower().strip(".") not in EMPTY_ANSWERS:
            actions.append({"action": action, "owner": owner, "due": due})

    return {
        "summary": tidy_text(data.get("summary")),
        "decisions": tidy_list(data.get("decisions")),
        "action_items": actions,
        "open_questions": tidy_list(data.get("open_questions")),
    }


def notes_from_model(messages: list[dict]) -> tuple[Optional[dict], str]:
    """
    Ask the model for notes. If the answer isn't valid JSON, ask once more.
    Returns (notes, raw answer) — notes is None if both answers were unusable.
    """
    reply = ask_model(messages)
    notes = parse_notes(reply)
    if notes is not None:
        return notes, reply

    print("   The AI's answer wasn't in the expected format — asking it once more...")
    retry = messages + [
        # Only show the model the start of its bad answer, to keep things short
        {"role": "assistant", "content": reply[:2000]},
        {"role": "user", "content": RETRY_INSTRUCTIONS},
    ]
    second_reply = ask_model(retry)
    notes = parse_notes(second_reply)
    # If even the second answer is unusable, keep whichever one has more text
    best_raw = second_reply if len(second_reply.strip()) >= len(reply.strip()) else reply
    return notes, (second_reply if notes else best_raw)


def summary_messages(text: str, part: int = 1, parts: int = 1) -> list[dict]:
    """The conversation we send for one transcript (or one part of a long one)."""
    if parts > 1:
        intro = (
            f"This is part {part} of {parts} of a longer meeting. "
            "Write notes for this part only."
        )
    else:
        intro = "Here is the meeting transcript."
    return [
        {"role": "system", "content": SUMMARY_INSTRUCTIONS},
        {"role": "user", "content": f'{intro}\n\nTRANSCRIPT:\n"""\n{text}\n"""'},
    ]


def combine_messages(partials: list[dict]) -> list[dict]:
    """The conversation we send to turn the notes of every part into one set."""
    numbered = [{"part": number, **notes} for number, notes in enumerate(partials, start=1)]
    return [
        {"role": "system", "content": COMBINE_INSTRUCTIONS},
        {
            "role": "user",
            "content": "PARTIAL NOTES:\n" + json.dumps(numbered, ensure_ascii=False, indent=1),
        },
    ]


def without_repeats(items: list, key=lambda item: item) -> list:
    """Remove items that appear twice (ignoring upper/lower case), keeping the order."""
    seen, kept = set(), []
    for item in items:
        marker = key(item).lower().strip(" .")
        if marker not in seen:
            seen.add(marker)
            kept.append(item)
    return kept


def join_parts(partials: list[dict]) -> dict:
    """Combine the notes of every part one after another (no AI needed)."""
    return {
        "summary": " ".join(notes["summary"] for notes in partials if notes["summary"]),
        "decisions": without_repeats([d for notes in partials for d in notes["decisions"]]),
        "action_items": without_repeats(
            [a for notes in partials for a in notes["action_items"]], key=lambda a: a["action"]
        ),
        "open_questions": without_repeats([q for notes in partials for q in notes["open_questions"]]),
    }


def combine_parts(partials: list[dict]) -> dict:
    """
    Ask the model to merge the notes of every part into one set of notes.

    Small models sometimes "forget" items when combining. As a safety net, if
    a combined list is less than half as long as the lists we started with,
    we keep the complete list from the parts instead.
    """
    joined = join_parts(partials)
    combined, _raw = notes_from_model(combine_messages(partials))
    if combined is None:
        print("   (The parts couldn't be combined neatly, so they were joined one after another.)")
        return joined

    for section in ("decisions", "action_items", "open_questions"):
        if len(combined[section]) * 2 < len(joined[section]):
            combined[section] = joined[section]
    if not combined["summary"]:
        combined["summary"] = joined["summary"]
    return combined


def summarise_meeting(text: str) -> tuple[Optional[dict], list[str]]:
    """
    Turn a whole transcript into notes, splitting long meetings into parts.
    Returns (notes, raw_answers): notes is None if nothing could be organised,
    and raw_answers holds any answers that weren't in the right format.
    """
    chunks = split_into_chunks(text, CHUNK_WORDS)

    if len(chunks) == 1:
        print("   Asking the AI model to write the notes (this can take a minute)...", flush=True)
        notes, raw = notes_from_model(summary_messages(chunks[0]))
        return notes, ([] if notes else [raw])

    print(f"   Long meeting: split into {len(chunks)} parts of up to {CHUNK_WORDS:,} words.")
    partials, raw_answers = [], []
    for number, chunk in enumerate(chunks, start=1):
        print(f"   Writing notes for part {number} of {len(chunks)}...", flush=True)
        notes, raw = notes_from_model(summary_messages(chunk, number, len(chunks)))
        if notes:
            partials.append(notes)
        else:
            raw_answers.append(raw)

    if not partials:
        return None, raw_answers
    if len(partials) == 1:
        return partials[0], raw_answers
    print(f"   Combining the {len(partials)} parts into one set of notes...", flush=True)
    return combine_parts(partials), raw_answers


def title_from_filename(source: Path) -> str:
    """Make a readable title from a file name: 'team_standup-2024' → 'Team standup 2024'."""
    words = re.sub(r"[_\-]+", " ", source.stem).strip()
    words = re.sub(r"\s+", " ", words)
    return (words[:1].upper() + words[1:]) if words else "Meeting"


def table_cell(text: str) -> str:
    """Make text safe inside a Markdown table cell (a '|' would start a new column)."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build_notes_file(source: Path, notes: Optional[dict], raw_answers: list[str]) -> str:
    """Put together the finished notes file in Markdown."""
    lines = [
        f"# Meeting notes: {title_from_filename(source)}",
        "",
        f"- Created: {datetime.now():%Y-%m-%d %H:%M}",
        f"- From: {source.name}",
        f"- Written by: the '{MODEL}' AI model, running on this computer",
        "- ⚠️ These notes were written automatically. Check them against the "
        "transcript before sharing.",
        "",
    ]

    if notes is not None:
        lines += ["## Summary", "", notes["summary"] or "No summary was written.", ""]

        lines += ["## Key decisions", ""]
        lines += [f"- {item}" for item in notes["decisions"]] or ["- None found in the transcript."]
        lines.append("")

        lines += ["## Action items", ""]
        if notes["action_items"]:
            lines += ["| Action | Owner | Due |", "|---|---|---|"]
            for item in notes["action_items"]:
                lines.append(
                    f"| {table_cell(item['action'])} | {table_cell(item['owner'])} "
                    f"| {table_cell(item['due'])} |"
                )
        else:
            lines.append("No action items were found in the transcript.")
        lines.append("")

        lines += ["## Open questions", ""]
        lines += [f"- {item}" for item in notes["open_questions"]] or ["- None found in the transcript."]
        lines.append("")

    if raw_answers:
        lines += [
            "## Notes that could not be organised automatically",
            "",
            "The AI model's answer below was not in the expected format, so it is",
            "saved exactly as written. Please tidy it up by hand.",
            "",
        ]
        for answer in raw_answers:
            lines += ["```text", answer.strip() or "(the model gave an empty answer)", "```", ""]

    return "\n".join(lines)


def choose_destination(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick an output filename that won't silently overwrite other notes from
    the *same* run. Re-running the script replaces older notes.

    Normal case:  standup.md   →  standup_notes.md
    Name clash:   standup.txt also in this batch → standup_txt_notes.md
    """
    base = f"{source.stem}_notes.md"
    if base.lower() not in used_names:
        used_names.add(base.lower())
        return output_dir / base

    fallback = f"{source.stem}_{source.suffix.lower().lstrip('.')}_notes.md"
    used_names.add(fallback.lower())
    return output_dir / fallback


def summarise_one_file(
    source: Path, output_dir: Path, index: int, total: int, used_names: set[str]
) -> bool:
    """Read one transcript, write its notes, and print progress.
    Returns True if notes were saved."""
    print(f"Summarising file {index} of {total}: {source.name} ...")
    started = time.monotonic()

    try:
        # utf-8-sig quietly removes the invisible marker Notepad sometimes adds
        raw = source.read_text(encoding="utf-8-sig", errors="replace")
        text, what_we_did = clean_transcript(raw)
        word_count = len(text.split())

        if word_count == 0:
            raise FriendlyError("the file is empty, so there is nothing to summarise.")
        if word_count < MIN_WORDS:
            raise FriendlyError(
                f"it only has {word_count} word(s), which is too short to make notes from."
            )

        detail = {
            "transcriber": " (Audio Transcriber file — timestamps left out)",
            "timestamps": " (timestamps left out)",
            "plain": "",
        }[what_we_did]
        print(f"   Reading: about {word_count:,} words{detail}")

        notes, raw_answers = summarise_meeting(text)
        destination = choose_destination(source, output_dir, used_names)
        # Build the whole file first, then write it in one go, so a problem
        # never leaves a half-finished file behind.
        destination.write_text(build_notes_file(source, notes, raw_answers), encoding="utf-8")
    except FriendlyError as err:
        print(f"   ⚠️  Skipped this file — {err}")
        print()
        return False
    except Exception as err:
        # Don't crash the whole batch if one file fails in an unexpected way
        print(f"   ⚠️  Skipped this file — something went wrong: {err}")
        print()
        return False

    elapsed = format_length(time.monotonic() - started)
    if notes is None:
        print("   ⚠️  The AI's answer still wasn't in the expected format, so it was")
        print("      saved as it is. Please tidy the notes by hand.")
    else:
        print(
            f"   Done! {len(notes['decisions'])} decision(s), "
            f"{len(notes['action_items'])} action item(s), "
            f"{len(notes['open_questions'])} open question(s) in {elapsed}."
        )
        if raw_answers:
            print(f"   ⚠️  {len(raw_answers)} part(s) couldn't be organised — "
                  "they were saved as they are at the end of the notes.")
    print(f"   Saved as: {destination.name}")
    print()
    return True


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python meeting_summarizer.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Meeting Notes Summarizer")
    print("=" * 60)
    print()
    print("Everything runs on this computer — your transcripts are never uploaded.")
    print()

    input_dir, output_dir = ensure_folders()
    transcripts = find_transcripts(input_dir)

    if not transcripts:
        print("No transcripts found yet.")
        print()
        print("What to do next:")
        print("  1. Turn recordings into transcripts with the Audio Transcriber")
        print(f"     (python audio_transcriber.py) — they are saved in '{INPUT_FOLDER_NAME}'.")
        print(f"     Or copy your own .txt / .md meeting notes into '{INPUT_FOLDER_NAME}'.")
        print("  2. Make sure the Ollama app is installed and open")
        print("     (free from https://ollama.com).")
        print("  3. Run this script again:")
        print()
        print("         python meeting_summarizer.py")
        print()
        return

    total = len(transcripts)
    print(f"Found {total} transcript(s) to summarise.")
    print()

    # Checking Ollama (and downloading the model the first time) happens once
    # for the whole batch, before any notes are written.
    prepare_model()

    # Track names we already wrote this run so standup.txt + standup.md
    # don't overwrite each other.
    used_names: set[str] = set()
    saved = 0

    for i, transcript in enumerate(transcripts, start=1):
        if summarise_one_file(transcript, output_dir, i, total, used_names):
            saved += 1

    print("=" * 60)
    print(f"All done! Wrote notes for {saved} of {total} transcript(s).")
    print(f"Check the '{OUTPUT_FOLDER_NAME}' folder for your .md files.")
    print(f"Transcripts in '{INPUT_FOLDER_NAME}' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

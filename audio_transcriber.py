#!/usr/bin/env python3
"""
Audio-to-Text Transcriber
=========================
This script looks in an "input_audio" folder for recordings (meetings, voice
memos, interviews, phone recordings, even videos) and writes down everything
that was said. Each recording gets its own text file in "transcripts", with a
timestamp in front of every line so you can find any moment quickly.

Everything happens on YOUR computer. The speech recognition model is downloaded
once (the first time you run the script); after that it works fully offline.
Your recordings are never uploaded anywhere, so private meetings stay private.

Your original recordings are never changed.

How to run (after following README.md):
    python audio_transcriber.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus faster-whisper for speech recognition
# ---------------------------------------------------------------------------

import os  # Lets us set a few download options before loading the library
import sys  # Gives access to the terminal output settings
import time  # Measures how long each recording took
import warnings  # Lets us hide harmless maths warnings (see below)
from datetime import datetime  # Puts today's date in each transcript
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple

# The speech model is downloaded from Hugging Face (a popular website for
# sharing these models). These options must be set BEFORE the import:
#   - turn off the optional usage statistics the download library can send
#   - hide a confusing Windows-only warning about "symlinks" (it is harmless)
#   - hide technical notes such as "set a HF_TOKEN for faster downloads",
#     which beginners don't need (real errors are still shown)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

# faster-whisper (installed via: pip install faster-whisper)
# It includes everything needed to read audio files, so you do NOT need to
# install any extra audio software. "av" is the audio reader that comes with it.
try:
    import av
    from faster_whisper import WhisperModel, available_models
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The faster-whisper library is not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install faster-whisper")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the recordings
INPUT_FOLDER_NAME = "input_audio"

# Folder where THIS SCRIPT saves the finished transcripts
OUTPUT_FOLDER_NAME = "transcripts"

# Which speech recognition model to use. Bigger = more accurate but slower,
# and a bigger one-time download. Rough times for a 10-minute recording
# (newer laptops are at the fast end, older ones at the slow end):
#   "tiny"   — ~75 MB download.  15 seconds to 1 minute. Fine for clear,
#              simple speech; trips up on names and accents.
#   "base"   — ~145 MB download. 30 seconds to 2 minutes. Good everyday
#              balance (the default).
#   "small"  — ~485 MB download. About 3 times slower than "base", but
#              noticeably better with accents, background noise, and names.
#   "medium" — ~1.5 GB download. About 3 times slower again. Most accurate
#              option here; needs a fast computer and several GB of free memory.
# (Advanced: you can also choose a model for a single run without editing this
# file by setting the AUDIO_TRANSCRIBER_MODEL_SIZE environment variable.)
MODEL_SIZE = os.environ.get("AUDIO_TRANSCRIBER_MODEL_SIZE", "base")

# Approximate download sizes, shown on the first run so the wait makes sense
MODEL_DOWNLOAD_SIZES = {
    "tiny": "75 MB",
    "base": "145 MB",
    "small": "485 MB",
    "medium": "1.5 GB",
}

# Language spoken in the recordings. None = detect it automatically from each
# recording. If detection guesses wrong (common with short clips or heavy
# accents), force it with a two-letter code, for example:
#   LANGUAGE = "en"   (English)    LANGUAGE = "es"   (Spanish)
#   LANGUAGE = "fr"   (French)     LANGUAGE = "de"   (German)
LANGUAGE = None

# How the model runs. "cpu" works on every computer (no graphics card needed).
# "int8" is a lighter maths mode: much faster and uses less memory, with almost
# no loss in accuracy.
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Print a progress line every time this much more of the recording is done,
# so long recordings never look frozen.
PROGRESS_EVERY_PERCENT = 10

# In the plain-text version, start a new paragraph when the speaker pauses
# for at least this many seconds. Makes long transcripts easier to read.
PARAGRAPH_PAUSE_SECONDS = 2.0

# File endings we accept as input (case-insensitive). Video files work too —
# only the sound is used. iPhone voice memos are .m4a files.
ALLOWED_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".flac",
    ".aac",
    ".wma",
    ".mp4",
    ".mov",
    ".webm",
}

# Friendly names for the most common languages (anything else shows its code)
LANGUAGE_NAMES = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "zh": "Chinese",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class SpokenLine(NamedTuple):
    """One piece of speech: when it started/ended (in seconds) and the words."""

    start: float
    end: float
    text: str


def format_clock(seconds: float) -> str:
    """Turn a number of seconds into a clock-style time like '00:01:23'."""
    seconds = max(0, int(seconds))  # Drop fractions: 83.9 seconds → 00:01:23
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_length(seconds: float) -> str:
    """Turn a number of seconds into friendly text like '3 min 12 sec'."""
    if seconds < 10:
        return f"{seconds:.1f} sec"
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} hr {minutes} min"
    if minutes:
        return f"{minutes} min {secs} sec"
    return f"{secs} sec"


def describe_language(code: str, probability: float) -> str:
    """Explain which language was used, e.g. 'English (detected automatically, 97% sure)'."""
    name = LANGUAGE_NAMES.get(code, code)
    if LANGUAGE:
        return f"{name} (set in the script's settings)"
    return f"{name} (detected automatically, {probability:.0%} sure)"


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
        print("   → Put your recordings (.mp3, .m4a, .wav, ...) in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_recordings(input_dir: Path) -> list[Path]:
    """Return a sorted list of audio/video files in the input folder (not subfolders)."""
    recordings = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._memo.m4a"
        # copies macOS leaves on USB drives — they are not real recordings.
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            recordings.append(item)

    # Sort alphabetically so "file 1 of 5" feels predictable
    return sorted(recordings, key=lambda p: p.name.lower())


def print_problem_box(lines: list[str]) -> None:
    """Print an important message inside a box of '=' signs so it stands out."""
    print()
    print("=" * 60)
    for line in lines:
        print(line)
    print("=" * 60)
    print()


def load_model() -> WhisperModel:
    """
    Load the speech recognition model once for the whole batch.

    We first look for a copy already saved on this computer. Only if there
    isn't one do we go online to download it. That way, every run after the
    first one works without internet and never contacts any website.
    """
    if MODEL_SIZE not in available_models():
        print_problem_box([
            f"Oops! '{MODEL_SIZE}' is not a speech model name this tool knows.",
            "Open audio_transcriber.py and set MODEL_SIZE to one of:",
            "",
            '    "tiny", "base", "small", or "medium"',
            "",
            'If you are not sure, use "base".',
        ])
        raise SystemExit(1)

    print(f"Loading the '{MODEL_SIZE}' speech recognition model...")

    try:
        model = WhisperModel(
            MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, local_files_only=True
        )
        print("   Ready! (found on this computer — no internet needed)")
        print()
        return model
    except Exception:
        pass  # Not downloaded yet (or the saved copy is incomplete) — fetch it below

    download_size = MODEL_DOWNLOAD_SIZES.get(MODEL_SIZE, "a few hundred MB")
    print(f"   First run: downloading the speech model (about {download_size}).")
    print("   This happens only once and can take a few minutes on slow internet.")
    print("   Only the model is downloaded — your recordings are NOT uploaded.")
    print("   After this, transcribing works fully offline.")

    try:
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    except Exception as err:
        print_problem_box([
            "Oops! The speech recognition model could not be downloaded.",
            f"The first run needs internet to fetch the '{MODEL_SIZE}' model",
            f"(about {download_size}). After that, no internet is needed.",
            "",
            "What to try:",
            "  1. Check your internet connection (or Wi-Fi sign-in page).",
            "  2. On a work network, a firewall may block huggingface.co —",
            "     try another network, such as home Wi-Fi.",
            "  3. Run this script again. Nothing was transcribed yet, and",
            "     your recordings were not changed.",
            "",
            f"Technical details: {err}",
        ])
        raise SystemExit(1)

    print("   Ready! Model downloaded and saved for next time.")
    print()
    return model


def listen_with_progress(segments, duration: float) -> list[SpokenLine]:
    """
    Collect the spoken lines one by one, printing a progress line every
    PROGRESS_EVERY_PERCENT so long recordings don't look frozen.

    The model works through the recording from start to finish and hands us
    each line as soon as it's ready, so "how far into the recording the latest
    line ends" tells us roughly how much is done.
    """
    lines: list[SpokenLine] = []
    next_report = PROGRESS_EVERY_PERCENT

    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(SpokenLine(segment.start, segment.end, text))

        if duration <= 0:
            continue
        percent = min(100, int(segment.end / duration * 100))
        if percent >= next_report:
            # flush=True shows the line immediately instead of waiting
            print(
                f"   Listening... {percent}% "
                f"({format_clock(segment.end)} of {format_clock(duration)})",
                flush=True,
            )
            # Jump to the next round number, e.g. from 37% to the 40% mark
            next_report = (percent // PROGRESS_EVERY_PERCENT + 1) * PROGRESS_EVERY_PERCENT

    return lines


def group_into_paragraphs(lines: list[SpokenLine]) -> list[str]:
    """Join spoken lines into paragraphs, starting a new one after a long pause."""
    paragraphs: list[list[str]] = []
    previous_end = None
    for line in lines:
        long_pause = previous_end is not None and line.start - previous_end >= PARAGRAPH_PAUSE_SECONDS
        if not paragraphs or long_pause:
            paragraphs.append([])
        paragraphs[-1].append(line.text)
        previous_end = line.end
    return [" ".join(words) for words in paragraphs]


def build_transcript(source_name: str, duration: float, language: str, lines: list[SpokenLine]) -> str:
    """
    Build the finished transcript text.

    We keep everything in ONE file per recording (rather than a second
    "_plain.txt" file) so the two versions can never get separated or mixed up:
      - the timestamped part is handy for jumping to a moment in the recording
      - the plain part at the bottom is ready to copy into an email, meeting
        minutes, or a document
    """
    divider = "-" * 60
    parts = [
        f"Transcript of: {source_name}",
        f"Length:        {format_length(duration)}",
        f"Language:      {language}",
        f"Speech model:  {MODEL_SIZE}",
        f"Created on:    {datetime.now():%Y-%m-%d %H:%M}",
        "",
        divider,
        "WITH TIMESTAMPS (hours:minutes:seconds into the recording)",
        divider,
        "",
    ]
    parts += [f"[{format_clock(line.start)}] {line.text}" for line in lines]
    parts += [
        "",
        divider,
        "PLAIN TEXT (ready to copy into an email or document)",
        divider,
        "",
    ]
    # A blank line between paragraphs makes them easy to tell apart
    parts.append("\n\n".join(group_into_paragraphs(lines)))
    return "\n".join(parts) + "\n"


def choose_destination(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick an output filename that won't silently overwrite another transcript
    from the *same* run. Re-running the script replaces older transcripts.

    Normal case:  standup.m4a  →  standup.txt
    Name clash:   standup.mp3 also in this batch → standup_mp3.txt
    """
    base = source.stem + ".txt"
    if base not in used_names:
        used_names.add(base)
        return output_dir / base

    fallback = f"{source.stem}_{source.suffix.lower().lstrip('.')}.txt"
    used_names.add(fallback)
    return output_dir / fallback


def explain_error(err: Exception) -> str:
    """Turn a technical error into a sentence a non-developer can act on."""
    if isinstance(err, av.error.FFmpegError):
        return (
            "this file could not be read as audio. It may be damaged, empty, or "
            "not really a sound file. Try opening it in a media player first."
        )
    return f"something went wrong: {err}"


def transcribe_one_file(
    model: WhisperModel,
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
) -> None:
    """Listen to one recording, save its transcript, and print progress."""
    print(f"Transcribing file {index} of {total}: {source.name} ...")
    started = time.monotonic()

    try:
        # The maths inside the speech library sometimes prints scary-looking
        # "divide by zero" warnings (especially around silent parts). They are
        # harmless and don't affect the transcript, so we hide them.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)

            # vad_filter=True skips silence (long pauses, hold music gaps), which
            # is faster and stops the model "hearing" words in background noise.
            segments, info = model.transcribe(str(source), language=LANGUAGE, vad_filter=True)
            print(f"   Length: {format_length(info.duration)}")
            lines = listen_with_progress(segments, info.duration)
    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — {explain_error(err)}")
        print()
        return

    if not lines:
        print(
            "   ⚠️  Skipped this file — no speech was found. The recording may be "
            "silent, very quiet, or only music."
        )
        print()
        return

    language = describe_language(info.language, info.language_probability)
    destination = choose_destination(source, output_dir, used_names)
    # utf-8 keeps accented letters and other alphabets (é, ñ, 日本) intact
    destination.write_text(
        build_transcript(source.name, info.duration, language, lines), encoding="utf-8"
    )

    elapsed = time.monotonic() - started
    print(f"   Language: {language}")
    print(f"   Done! {len(lines)} line(s) of speech transcribed in {format_length(elapsed)}.")
    print(f"   Saved as: {destination.name}")
    print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python audio_transcriber.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Audio-to-Text Transcriber")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    recordings = find_recordings(input_dir)

    if not recordings:
        print("No audio recordings found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your recordings into it")
        print("     (.mp3 / .m4a / .wav / .ogg / .flac / .aac / .wma,")
        print("      or videos: .mp4 / .mov / .webm).")
        print("  3. Run this script again:")
        print()
        print("         python audio_transcriber.py")
        print()
        return

    total = len(recordings)
    print(f"Found {total} recording(s) to transcribe.")
    print()

    # Loading the model takes a few seconds, so we do it once for the whole
    # batch instead of once per recording.
    model = load_model()

    # Track names we already wrote this run so standup.m4a + standup.mp3
    # don't overwrite each other.
    used_names: set[str] = set()

    for i, recording in enumerate(recordings, start=1):
        transcribe_one_file(model, recording, output_dir, i, total, used_names)

    print("=" * 60)
    print("All done! Check the 'transcripts' folder for your .txt files.")
    print("Originals in 'input_audio' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

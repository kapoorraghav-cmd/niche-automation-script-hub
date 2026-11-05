#!/usr/bin/env python3
"""
Video Subtitle Maker
====================
This script looks in an "input_videos" folder for videos (screen recordings,
training videos, webinars, social media clips — audio files work too) and
writes subtitles for everything that is said. Each video gets TWO subtitle
files in "subtitles", with the same words and timings in two common formats:

  1. <name>.srt — the most widely supported subtitle format. Upload it to
     YouTube, LinkedIn or Facebook, open it in VLC, or import it into video
     editors such as Premiere Pro, DaVinci Resolve, iMovie and CapCut.
  2. <name>.vtt — the "WebVTT" format used by web video players (HTML5 video,
     Vimeo, many online course and company video platforms) and by PowerPoint
     ("Insert Captions").

The captions are kept short and readable: at most 2 lines of about 42
characters, on screen for no more than about 6 seconds, and words are never
cut in half.

Everything happens on YOUR computer. The speech recognition model is downloaded
once (the first time you run the script); after that it works fully offline.
Your videos are never uploaded anywhere.

Your original videos are never changed.

How to run (after following README.md):
    python video_subtitles.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus faster-whisper for speech recognition
# ---------------------------------------------------------------------------

import os  # Lets us set a few download options before loading the library
import sys  # Gives access to the terminal output settings
import time  # Measures how long each video took
import warnings  # Lets us hide harmless maths warnings (see below)
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional

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
# It includes everything needed to read video and audio files, so you do NOT
# need to install ffmpeg or any other video software. "av" is the video/audio
# reader that comes with it.
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

# Folder where YOU put the videos
INPUT_FOLDER_NAME = "input_videos"

# Folder where THIS SCRIPT saves the finished subtitle files
OUTPUT_FOLDER_NAME = "subtitles"

# Which speech recognition model to use. Bigger = more accurate but slower,
# and a bigger one-time download. Rough times for a 10-minute video
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
# file by setting the VIDEO_SUBTITLES_MODEL_SIZE environment variable.)
MODEL_SIZE = os.environ.get("VIDEO_SUBTITLES_MODEL_SIZE", "base")

# Approximate download sizes, shown on the first run so the wait makes sense
MODEL_DOWNLOAD_SIZES = {
    "tiny": "75 MB",
    "base": "145 MB",
    "small": "485 MB",
    "medium": "1.5 GB",
}

# Language spoken in the videos. None = detect it automatically from each
# video. If detection guesses wrong (common with short clips or heavy
# accents), force it with a two-letter code, for example:
#   LANGUAGE = "en"   (English)    LANGUAGE = "es"   (Spanish)
#   LANGUAGE = "fr"   (French)     LANGUAGE = "de"   (German)
LANGUAGE = None

# False = subtitles in the language people are speaking (the usual choice).
# True  = English subtitles for videos in ANY language, for example a Spanish
#         webinar gets English captions. The model translates as it listens,
#         so it is roughly as fast as normal subtitles. Translation quality
#         is good enough to follow along, but proofread before publishing.
TRANSLATE_TO_ENGLISH = False

# How the model runs. "cpu" works on every computer (no graphics card needed).
# "int8" is a lighter maths mode: much faster and uses less memory, with almost
# no loss in accuracy.
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Print a progress line every time this much more of the video is done,
# so long videos never look frozen.
PROGRESS_EVERY_PERCENT = 10

# Caption size and timing. These follow common broadcast and streaming
# guidelines, so viewers can read every caption before it disappears:
#   - at most 42 letters/spaces per line (fits phone screens too)
#   - at most 2 lines on screen at once
#   - each caption stays up at most 6 seconds, and at least 1 second
#     (when the next caption doesn't start sooner)
#   - a pause in speech this long starts a fresh caption, so old words
#     don't hang on screen while nobody is talking
MAX_CHARS_PER_LINE = 42
MAX_LINES_PER_CAPTION = 2
MAX_CAPTION_SECONDS = 6.0
MIN_CAPTION_SECONDS = 1.0
NEW_CAPTION_AFTER_PAUSE_SECONDS = 1.5

# File endings we accept as input (case-insensitive). Audio files work too —
# handy for podcasts that will be turned into a video later.
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".wma"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

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

class SpokenWord(NamedTuple):
    """One spoken word: when it started/ended (in seconds) and the word itself."""

    start: float
    end: float
    text: str


class Caption(NamedTuple):
    """One subtitle that appears on screen: start/end time and 1–2 lines of text."""

    start: float
    end: float
    lines: list[str]


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


def format_subtitle_time(seconds: float, separator: str) -> str:
    """
    Turn seconds into a subtitle timestamp with milliseconds.

    The two formats differ by ONE character, and players are strict about it:
        SRT uses a comma:   00:01:02,345
        VTT uses a dot:     00:01:02.345
    """
    total_ms = max(0, round(seconds * 1000))  # Round, so 1.9996 s → 00:00:02,000
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def describe_language(code: str, probability: float) -> str:
    """Explain which language was used, e.g. 'English (detected automatically, 97% sure)'."""
    name = LANGUAGE_NAMES.get(code, code)
    if LANGUAGE:
        description = f"{name} (set in the script's settings)"
    else:
        description = f"{name} (detected automatically, {probability:.0%} sure)"
    if TRANSLATE_TO_ENGLISH and code != "en":
        description += " → subtitles translated to English"
    return description


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
        print("   → Put your videos (.mp4, .mov, .mkv, ...) in this folder, then run again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_videos(input_dir: Path) -> list[Path]:
    """Return a sorted list of video/audio files in the input folder (not subfolders)."""
    videos = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._clip.mp4"
        # copies macOS leaves on USB drives — they are not real videos.
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            videos.append(item)

    # Sort alphabetically so "file 1 of 5" feels predictable
    return sorted(videos, key=lambda p: p.name.lower())


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
            "Open video_subtitles.py and set MODEL_SIZE to one of:",
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
    print("   Only the model is downloaded — your videos are NOT uploaded.")
    print("   After this, making subtitles works fully offline.")

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
            "  3. Run this script again. No subtitles were made yet, and",
            "     your videos were not changed.",
            "",
            f"Technical details: {err}",
        ])
        raise SystemExit(1)

    print("   Ready! Model downloaded and saved for next time.")
    print()
    return model


def has_sound_track(source: Path) -> bool:
    """
    Check that the file actually contains sound. Some videos (screen
    recordings with the microphone off, silent stock footage) have pictures
    only, and there is nothing to make subtitles from.
    """
    with av.open(str(source)) as container:
        return len(container.streams.audio) > 0


def words_from_segment(segment) -> list[SpokenWord]:
    """
    Get the individual words of one piece of speech, each with its own timing.

    We ask the model for word-by-word timings, which lets us cut captions at
    exactly the right moment. In the rare case a piece of speech comes back
    without them, we share its time out across its words instead (longer
    words get a bit more time), which is still close enough to read along.
    """
    timed = getattr(segment, "words", None) or []
    words = [
        SpokenWord(float(w.start), max(float(w.start), float(w.end)), w.word.strip())
        for w in timed
        if w.word.strip()
    ]
    if words:
        return words

    pieces = segment.text.split()
    if not pieces:
        return []
    start, end = float(segment.start), max(float(segment.start), float(segment.end))
    total_letters = sum(len(piece) for piece in pieces)
    words, position = [], start
    for piece in pieces:
        share = (end - start) * len(piece) / total_letters
        words.append(SpokenWord(position, position + share, piece))
        position += share
    return words


def listen_with_progress(segments, duration: float) -> list[SpokenWord]:
    """
    Collect every spoken word, printing a progress line every
    PROGRESS_EVERY_PERCENT so long videos don't look frozen.

    The model works through the video from start to finish and hands us each
    piece of speech as soon as it's ready, so "how far into the video the
    latest piece ends" tells us roughly how much is done.
    """
    words: list[SpokenWord] = []
    next_report = PROGRESS_EVERY_PERCENT

    for segment in segments:
        words.extend(words_from_segment(segment))

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

    return words


def wrap_into_lines(words: list[str]) -> Optional[list[str]]:
    """
    Arrange words into caption lines, or return None if they don't fit.

    Words are never split in half. A single word longer than a whole line
    (for example a long web address) gets a line to itself rather than
    being cut.
    """
    # Fill each line as full as possible. This uses the fewest lines.
    lines = []
    for word in words:
        if lines and len(lines[-1]) + 1 + len(word) <= MAX_CHARS_PER_LINE:
            lines[-1] += " " + word
        else:
            lines.append(word)

    if len(lines) > MAX_LINES_PER_CAPTION:
        return None

    # Two lines look best when they are about the same length (a long top
    # line with one lonely word below is harder to read), so try every place
    # to break and keep the most even one that still fits.
    if len(lines) == 2:
        best = lines
        for cut in range(1, len(words)):
            top, bottom = " ".join(words[:cut]), " ".join(words[cut:])
            if max(len(top), len(bottom)) < max(len(best[0]), len(best[1])):
                best = [top, bottom]
        lines = best

    return lines


def ends_sentence(word: str) -> bool:
    """True if the word finishes a sentence, e.g. 'morning.' or 'Friday?"'"""
    return word.rstrip("\"')]»”’").endswith((".", "?", "!", "…", "。", "？", "！"))


def build_captions(words: list[SpokenWord], duration: float = 0.0) -> list[Caption]:
    """
    Group the spoken words into short, readable captions.

    We add words to the current caption one at a time, and start a new
    caption when the next word would:
      - need more than MAX_LINES_PER_CAPTION lines of MAX_CHARS_PER_LINE,
      - keep the caption on screen longer than MAX_CAPTION_SECONDS,
      - come after a long pause in speech,
    or when the previous sentence has just ended (captions that begin with
    a new sentence are much easier to follow).
    """
    groups: list[list[SpokenWord]] = []
    for word in words:
        if groups:
            current = groups[-1]
            too_long = word.end - current[0].start > MAX_CAPTION_SECONDS
            long_pause = word.start - current[-1].end >= NEW_CAPTION_AFTER_PAUSE_SECONDS
            too_wide = wrap_into_lines([w.text for w in current + [word]]) is None
            if not (too_long or long_pause or too_wide or ends_sentence(current[-1].text)):
                current.append(word)
                continue
        groups.append([word])

    captions = []
    for i, group in enumerate(groups):
        start = group[0].start
        # Keep very short captions (a quick "Yes.") on screen for at least
        # MIN_CAPTION_SECONDS so people can read them — but never let one
        # overlap the next caption or run past the end of the video.
        end = max(group[-1].end, start + MIN_CAPTION_SECONDS)
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0].start)
        if duration > 0:
            end = min(end, duration)
        end = max(end, start + 0.001)  # A caption must end after it starts
        captions.append(Caption(start, end, wrap_into_lines([w.text for w in group])))
    return captions


def build_srt(captions: list[Caption]) -> str:
    """
    Build an .srt subtitle file. Each caption is:
        a number, starting at 1
        start --> end   (with a comma before the milliseconds)
        1 or 2 lines of text
        an empty line
    """
    blocks = []
    for number, caption in enumerate(captions, start=1):
        timing = (
            f"{format_subtitle_time(caption.start, ',')} --> "
            f"{format_subtitle_time(caption.end, ',')}"
        )
        blocks.append("\n".join([str(number), timing, *caption.lines]))
    return "\n\n".join(blocks) + "\n"


def build_vtt(captions: list[Caption]) -> str:
    """
    Build a .vtt (WebVTT) subtitle file. It must start with the word WEBVTT,
    uses a dot before the milliseconds, and doesn't need caption numbers.
    Web players treat "<" and "&" as special codes, so we write them in the
    safe form "&lt;" and "&amp;" (they still show up as < and & on screen).
    """
    blocks = ["WEBVTT"]
    for caption in captions:
        timing = (
            f"{format_subtitle_time(caption.start, '.')} --> "
            f"{format_subtitle_time(caption.end, '.')}"
        )
        lines = [
            line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            for line in caption.lines
        ]
        blocks.append("\n".join([timing, *lines]))
    return "\n\n".join(blocks) + "\n"


def choose_base_name(source: Path, used_names: set[str]) -> str:
    """
    Pick an output name that won't silently overwrite subtitles from the
    *same* run. Re-running the script replaces older subtitles.

    Normal case:  webinar.mp4  →  webinar.srt + webinar.vtt
    Name clash:   webinar.mov also in this batch → webinar_mov.srt + .vtt
    """
    base = source.stem
    if base.lower() not in used_names:
        used_names.add(base.lower())
        return base

    fallback = f"{source.stem}_{source.suffix.lower().lstrip('.')}"
    used_names.add(fallback.lower())
    return fallback


def explain_error(err: Exception) -> str:
    """Turn a technical error into a sentence a non-developer can act on."""
    if isinstance(err, av.error.FFmpegError):
        return (
            "this file could not be read as a video or audio file. It may be "
            "damaged, empty, or still downloading. Try playing it in a media player first."
        )
    return f"something went wrong: {err}"


def subtitle_one_file(
    model: WhisperModel,
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
) -> None:
    """Listen to one video, save its .srt and .vtt subtitles, and print progress."""
    print(f"Making subtitles {index} of {total}: {source.name} ...")
    started = time.monotonic()

    try:
        if not has_sound_track(source):
            print(
                "   ⚠️  Skipped this file — it has no sound track, so there is "
                "nothing to subtitle."
            )
            print()
            return

        # The maths inside the speech library sometimes prints scary-looking
        # "divide by zero" warnings (especially around silent parts). They are
        # harmless and don't affect the subtitles, so we hide them.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)

            # vad_filter=True skips silence (long pauses, music-only parts),
            # which is faster and stops the model "hearing" words in noise.
            # word_timestamps=True gives each word its own timing, so every
            # caption appears exactly when its words are spoken.
            # task="translate" turns any language into English subtitles.
            segments, info = model.transcribe(
                str(source),
                language=LANGUAGE,
                task="translate" if TRANSLATE_TO_ENGLISH else "transcribe",
                vad_filter=True,
                word_timestamps=True,
            )
            print(f"   Length: {format_length(info.duration)}")
            words = listen_with_progress(segments, info.duration)
    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — {explain_error(err)}")
        print()
        return

    if not words:
        print(
            "   ⚠️  Skipped this file — no speech was found. The video may be "
            "silent, very quiet, or only music."
        )
        print()
        return

    captions = build_captions(words, info.duration)
    base = choose_base_name(source, used_names)
    # utf-8 keeps accented letters and other alphabets (é, ñ, 日本) intact
    (output_dir / f"{base}.srt").write_text(build_srt(captions), encoding="utf-8")
    (output_dir / f"{base}.vtt").write_text(build_vtt(captions), encoding="utf-8")

    elapsed = time.monotonic() - started
    print(f"   Language: {describe_language(info.language, info.language_probability)}")
    print(f"   Done! {len(captions)} caption(s) made in {format_length(elapsed)}.")
    print(f"   Saved as: {base}.srt and {base}.vtt")
    print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python video_subtitles.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Video Subtitle Maker")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    videos = find_videos(input_dir)

    if not videos:
        print("No videos found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your videos into it")
        print("     (.mp4 / .mov / .m4v / .mkv / .webm / .avi,")
        print("      or audio: .mp3 / .m4a / .wav / .ogg / .flac / .aac / .wma).")
        print("  3. Run this script again:")
        print()
        print("         python video_subtitles.py")
        print()
        return

    total = len(videos)
    print(f"Found {total} video(s) to subtitle.")
    print()

    # Loading the model takes a few seconds, so we do it once for the whole
    # batch instead of once per video.
    model = load_model()

    # Track names we already wrote this run so talk.mp4 + talk.mov
    # don't overwrite each other.
    used_names: set[str] = set()

    for i, video in enumerate(videos, start=1):
        subtitle_one_file(model, video, output_dir, i, total, used_names)

    print("=" * 60)
    print("All done! Check the 'subtitles' folder for your .srt and .vtt files.")
    print("Originals in 'input_videos' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

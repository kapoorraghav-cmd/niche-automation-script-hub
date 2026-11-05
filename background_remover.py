#!/usr/bin/env python3
"""
Background Remover
==================
This script looks in an "input_photos" folder, finds the main subject in every
photo (a product, a person, a pet...) and cuts the background away. Each result
is saved as a PNG file in "no_background", with a see-through (transparent)
background — ready for online shops, slides, flyers, or ID-style photos.

It uses a small AI model that runs on YOUR computer. The model is downloaded
once (the first time you run the script); after that it works fully offline.
Your photos are never uploaded anywhere.

Your original photos are never changed.

How to run (after following README.md):
    python background_remover.py
"""

# ---------------------------------------------------------------------------
# Imports — built-in tools plus onnxruntime, numpy and Pillow
# ---------------------------------------------------------------------------

import hashlib  # Checks that the downloaded model is complete and genuine
import io  # Lets us build a file in memory before saving it to disk
import os  # Reads an optional setting and safely renames finished downloads
import socket  # Recognizes "the internet connection timed out" errors
import sys  # Gives access to the terminal output settings
import urllib.error  # Recognizes "no internet" errors
import urllib.request  # Downloads the model the first time
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional

# onnxruntime runs the AI model, numpy does the maths on the model's answer,
# and Pillow opens, edits and saves the pictures.
# (installed via: pip install onnxruntime numpy Pillow)
try:
    import numpy as np
    import onnxruntime
    from PIL import Image, ImageColor, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError as import_error:
    print()
    print("=" * 60)
    if "DLL load failed" in str(import_error):
        # Windows only: onnxruntime is installed, but a free Microsoft
        # component it relies on is missing from this computer.
        print("Oops! onnxruntime is installed but Windows could not start it.")
        print("Install the free 'Microsoft Visual C++ Redistributable' from:")
        print()
        print("    https://aka.ms/vs/17/release/vc_redist.x64.exe")
        print()
        print("Restart your computer, then run this script again.")
    else:
        print("Oops! A library this tool needs is not installed yet.")
        print("Open your terminal in this project folder and run:")
        print()
        print("    pip install onnxruntime numpy Pillow")
        print()
        print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the original photos
INPUT_FOLDER_NAME = "input_photos"

# Folder where THIS SCRIPT saves the finished .png files
OUTPUT_FOLDER_NAME = "no_background"

# What to put behind the subject:
#   None     — nothing: a see-through (transparent) background. Best for online
#              shops, slides and designs where you place the cut-out yourself.
#   "white"  — a plain white background. Handy for ID, passport and visa
#              photos, which usually must have a plain light background.
#              (Always check the official rules for your country: many also
#              require a certain size and head position.)
# You can use any color name ("white", "lightgray", "skyblue") or a web color
# code such as "#F0F0F0".
BACKGROUND_COLOR = None

# True = trim the empty space around the subject (keeping a small margin), so
# a small product in a big photo fills the picture. False = keep the full
# photo size, with the subject exactly where it was.
CROP_TO_SUBJECT = False

# Margin kept around the subject when CROP_TO_SUBJECT is True, as a percentage
# of the subject's size (5 = a thin border of 5%).
CROP_MARGIN_PERCENT = 5

# How soft the edge of the cut-out is. 0 = exactly as the model drew it.
# Try 1 or 2 if edges look jagged or "cut out with scissors"; higher values
# give a dreamier, feathered edge.
EDGE_SOFTNESS = 0

# Which AI model finds the subject. Each one is downloaded once, the first
# time you use it, and then works offline.
#   "u2net"             — ~168 MB. Best all-rounder for products, people and
#                         pets (the default).
#   "u2netp"            — ~4.4 MB. Tiny and fast. Fine for simple photos (one
#                         object on a plain background), but may miss parts
#                         of a person or object.
#   "u2net_human_seg"   — ~168 MB. Trained only on people: try it for
#                         headshots and ID photos. Poor at products.
#   "isnet-general-use" — ~170 MB. A newer model that sometimes keeps finer
#                         detail, but in our tests it more often left faint
#                         streaks or see-through patches. About 3 times slower.
# All four were made freely available by their authors (Xuebin Qin and
# colleagues) under the Apache License 2.0, which allows any use, including
# commercial. The ready-to-use copies are hosted by the rembg project (MIT).
# (Advanced: you can also choose a model for a single run without editing this
# file by setting the BACKGROUND_REMOVER_MODEL environment variable.)
MODEL = os.environ.get("BACKGROUND_REMOVER_MODEL", "u2net")

# Where downloaded models are kept, shared by every project folder on this
# computer. You can delete this folder at any time to free up space; the model
# will simply be downloaded again next time.
MODEL_FOLDER = Path.home() / ".cache" / "niche-automation-script-hub" / "models"

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


# ---------------------------------------------------------------------------
# Model details — you don't need to change anything in this section
# ---------------------------------------------------------------------------

class ModelInfo(NamedTuple):
    """Everything we need to know to download and use one model."""

    file_name: str  # Name of the model file
    download_size: str  # Friendly size shown before the first download
    sha256: str  # The file's "fingerprint", used to check the download
    input_size: int  # The model looks at photos shrunk to this many pixels square
    mean: tuple  # Color adjustments the model was trained with
    std: tuple


# Where the models are downloaded from (the rembg project's GitHub page)
MODEL_DOWNLOAD_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/{}"

# Standard color adjustments used by the U-2-Net models
U2NET_MEAN = (0.485, 0.456, 0.406)
U2NET_STD = (0.229, 0.224, 0.225)

AVAILABLE_MODELS = {
    "u2net": ModelInfo(
        "u2net.onnx", "168 MB",
        "8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491",
        320, U2NET_MEAN, U2NET_STD,
    ),
    "u2netp": ModelInfo(
        "u2netp.onnx", "4.4 MB",
        "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8",
        320, U2NET_MEAN, U2NET_STD,
    ),
    "u2net_human_seg": ModelInfo(
        "u2net_human_seg.onnx", "168 MB",
        "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c",
        320, U2NET_MEAN, U2NET_STD,
    ),
    "isnet-general-use": ModelInfo(
        "isnet-general-use.onnx", "170 MB",
        "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
        1024, (0.5, 0.5, 0.5), (1.0, 1.0, 1.0),
    ),
}

# The model gives every pixel a score from 0 (background) to 1 (subject).
# Pixels scoring above this count as "subject".
SUBJECT_SCORE = 0.5

# If less than this share of the photo (0.005 = 0.5%) is subject, we warn that
# no clear subject was found.
MIN_SUBJECT_SHARE = 0.005

# Download in pieces of this many bytes (1 MB), printing progress as we go
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# Print a download progress line every time this much more is done
PROGRESS_EVERY_PERCENT = 10


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class BackgroundModel(NamedTuple):
    """The loaded AI model plus the details needed to use it."""

    session: object  # onnxruntime's "inference session" that runs the model
    info: ModelInfo


class SubjectMask(NamedTuple):
    """What the model found in one photo."""

    mask: Image.Image  # Black-and-white picture: white = keep, black = remove
    subject_share: float  # How much of the photo is subject (0.0 to 1.0)
    subject_found: bool  # False if the model found nothing clear


class DownloadCheckFailed(Exception):
    """The downloaded file's fingerprint did not match the expected one."""


def format_size(num_bytes: int) -> str:
    """Turn a raw byte count into a friendly size like '142.3 KB'."""
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.2f} MB"


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
        print("   → Put your photos (.jpg, .png, .webp) in this folder, then run the script again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_photos(input_dir: Path) -> list[Path]:
    """Return a sorted list of photos inside the input folder (not subfolders)."""
    photos = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._photo.jpg"
        # copies macOS leaves on USB drives — they are not real pictures.
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            photos.append(item)

    # Sort alphabetically so "photo 1 of 5" feels predictable
    return sorted(photos, key=lambda p: p.name.lower())


def background_fill() -> Optional[tuple]:
    """
    Turn the BACKGROUND_COLOR setting into a color the script can use.
    Returns None for a transparent background. Stops with a friendly
    message if the color name isn't recognized.
    """
    if BACKGROUND_COLOR is None:
        return None
    try:
        return ImageColor.getrgb(str(BACKGROUND_COLOR))[:3]
    except ValueError:
        print_problem_box([
            f"Oops! '{BACKGROUND_COLOR}' is not a color this tool knows.",
            "Open background_remover.py and set BACKGROUND_COLOR to, for example:",
            "",
            '    None        (see-through background)',
            '    "white"     (for ID / passport-style photos)',
            '    "#F0F0F0"   (a web color code)',
        ])
        raise SystemExit(1)


def file_fingerprint(path: Path) -> str:
    """Work out a file's SHA-256 "fingerprint" (it changes if even one byte differs)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, expected_sha256: str) -> None:
    """
    Download a file with progress messages, check its fingerprint, and only
    then move it into place.

    The download is first saved under a temporary ".part" name. If the internet
    drops halfway, or the file isn't exactly the one we expect, the temporary
    file is deleted — so a broken model can never be left behind.
    """
    temporary = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "niche-automation-script-hub"})

    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(temporary, "wb") as f:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            next_report = PROGRESS_EVERY_PERCENT
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)

                if total:
                    percent = min(100, int(done / total * 100))
                    if percent >= next_report:
                        # flush=True shows the line immediately instead of waiting
                        print(
                            f"   Downloading... {percent}% "
                            f"({done / 1024 / 1024:.1f} of {total / 1024 / 1024:.1f} MB)",
                            flush=True,
                        )
                        next_report = (percent // PROGRESS_EVERY_PERCENT + 1) * PROGRESS_EVERY_PERCENT

        if digest.hexdigest() != expected_sha256:
            raise DownloadCheckFailed(
                f"expected fingerprint {expected_sha256[:12]}…, got {digest.hexdigest()[:12]}…"
            )
        # os.replace swaps the finished file into place in one step
        os.replace(temporary, destination)
    finally:
        # Tidy up the temporary file if anything above went wrong
        if temporary.exists():
            temporary.unlink()


def is_internet_problem(err: Exception) -> bool:
    """True for errors that mean "couldn't reach the website"."""
    return isinstance(err, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError))


def ensure_model_file(name: str, info: ModelInfo) -> Path:
    """
    Return the path of the model file, downloading it first if this computer
    doesn't have a good copy yet. Stops with a friendly message if that fails.
    """
    model_path = MODEL_FOLDER / info.file_name

    if model_path.exists():
        if file_fingerprint(model_path) == info.sha256:
            print("   Ready! (found on this computer — no internet needed)")
            return model_path
        print("   The saved copy of the model looks incomplete or damaged,")
        print("   so it will be downloaded again.")

    print(f"   First run: downloading the model (about {info.download_size}).")
    print("   This happens only once and can take a few minutes on slow internet.")
    print("   Only the model is downloaded — your photos are NOT uploaded.")
    print(f"   It will be saved in: {MODEL_FOLDER}")

    url = MODEL_DOWNLOAD_URL.format(info.file_name)
    try:
        MODEL_FOLDER.mkdir(parents=True, exist_ok=True)
        download_file(url, model_path, info.sha256)
    except DownloadCheckFailed as err:
        print_problem_box([
            "Oops! The downloaded model did not pass its safety check.",
            "The file was incomplete or not the one this tool expects,",
            "so it was deleted and NOT used.",
            "",
            "What to try:",
            "  1. Run this script again — a hiccup in the download is the",
            "     most common cause.",
            "  2. On a work network, a firewall or proxy may be changing",
            "     downloads — try another network, such as home Wi-Fi.",
            "",
            f"Technical details: {err}",
        ])
        raise SystemExit(1)
    except Exception as err:
        if is_internet_problem(err):
            lines = [
                "Oops! The background removal model could not be downloaded.",
                f"The first run needs internet to fetch the '{name}' model",
                f"(about {info.download_size}). After that, no internet is needed.",
                "",
                "What to try:",
                "  1. Check your internet connection (or Wi-Fi sign-in page).",
                "  2. On a work network, a firewall may block github.com —",
                "     try another network, such as home Wi-Fi.",
                "  3. Or download the file yourself in a web browser:",
                f"       {url}",
                "     and put it in this folder:",
                f"       {MODEL_FOLDER}",
                "",
                "Your photos were not changed.",
            ]
            if "CERTIFICATE_VERIFY_FAILED" in str(err):
                lines += [
                    "",
                    "On a Mac, this error usually means Python's security",
                    "certificates aren't installed yet: open your Applications",
                    "folder → Python 3.x → double-click 'Install Certificates.command'.",
                ]
        else:
            lines = [
                "Oops! The model could not be saved on this computer.",
                f"Folder: {MODEL_FOLDER}",
                "Check that your disk isn't full, then run this script again.",
            ]
        print_problem_box(lines + ["", f"Technical details: {err}"])
        raise SystemExit(1)

    print("   Download checked: complete and genuine ✓")
    print("   Ready! Model downloaded and saved for next time.")
    return model_path


def load_model() -> BackgroundModel:
    """
    Load the background removal model once for the whole batch, downloading
    it first if needed.
    """
    info = AVAILABLE_MODELS.get(MODEL)
    if info is None:
        print_problem_box([
            f"Oops! '{MODEL}' is not a model name this tool knows.",
            "Open background_remover.py and set MODEL to one of:",
            "",
            '    "u2net", "u2netp", "u2net_human_seg", or "isnet-general-use"',
            "",
            'If you are not sure, use "u2net".',
        ])
        raise SystemExit(1)

    print(f"Loading the '{MODEL}' background removal model...")
    model_path = ensure_model_file(MODEL, info)

    # Only show onnxruntime's serious errors, not its technical notes
    onnxruntime.set_default_logger_severity(3)
    # Uses a few hundred MB less memory, at the same speed
    options = onnxruntime.SessionOptions()
    options.enable_mem_pattern = False
    try:
        # "CPU" works on every computer — no graphics card needed
        session = onnxruntime.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
    except Exception as err:
        print_problem_box([
            "Oops! The model was found but could not be started.",
            "Try deleting this file so it downloads fresh next time:",
            f"    {model_path}",
            "",
            f"Technical details: {err}",
        ])
        raise SystemExit(1)

    print()
    return BackgroundModel(session, info)


def open_photo(source: Path) -> tuple[Image.Image, Optional[Image.Image], Optional[bytes]]:
    """
    Open a photo the right way up and split it into its colors and (if it
    has one) its existing transparency.

    Returns (color_picture, existing_transparency_or_None, color_profile_or_None).
    """
    with Image.open(source) as img:
        # Phones sometimes store "rotate me" information instead of turning
        # the picture itself; this applies it so nothing comes out sideways.
        img = ImageOps.exif_transpose(img)
        img.load()

        if img.mode.startswith("I"):
            # High-precision (16-bit) black-and-white pictures, mostly from
            # scanners: scale them down to normal brightness levels first,
            # otherwise they would come out completely white.
            img = img.convert("I")
            if img.getextrema()[1] > 255:
                img = img.point(lambda value: value * (1 / 256))
            img = img.convert("L")

        # Keep the color profile so photos from modern phones don't look
        # faded — but only for normal color photos, where it still applies.
        icc_profile = img.info.get("icc_profile") if img.mode in ("RGB", "RGBA") else None

        has_alpha = img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info
        )
        if has_alpha:
            rgba = img.convert("RGBA")
            return rgba.convert("RGB"), rgba.getchannel("A"), icc_profile
        return img.convert("RGB"), None, icc_profile


def prepare_model_input(photo: Image.Image, info: ModelInfo) -> np.ndarray:
    """
    Shrink and adjust a photo into the exact format the model expects:
    a square of info.input_size pixels, with colors scaled the same way as
    the photos the model learned from.

    Returns numbers shaped (1, 3, size, size): one photo, three colors
    (red, green, blue), then height and width.
    """
    side = info.input_size
    # reducing_gap makes shrinking huge photos much faster, with the same quality
    small = photo.resize((side, side), Image.LANCZOS, reducing_gap=3.0)

    pixels = np.asarray(small, dtype=np.float32)
    # Scale brightness to 0–1 (relative to the brightest pixel, as the model
    # was trained), then apply the model's color adjustments.
    pixels = pixels / max(float(pixels.max()), 1e-6)
    pixels = (pixels - np.array(info.mean, dtype=np.float32)) / np.array(info.std, dtype=np.float32)

    # Reorder from (height, width, color) to (1, color, height, width)
    return pixels.transpose(2, 0, 1)[np.newaxis].astype(np.float32)


def scores_to_mask(raw_scores: np.ndarray, size: tuple[int, int]) -> SubjectMask:
    """
    Turn the model's answer into a black-and-white mask the size of the photo.

    The model gives each pixel a score: near 1 = subject, near 0 = background.
    """
    scores = np.asarray(raw_scores, dtype=np.float32)
    scores = scores.reshape(scores.shape[-2], scores.shape[-1])

    # Some model files give raw scores (any number) instead of 0–1. The
    # "sigmoid" formula squeezes those into 0–1.
    if scores.min() < 0 or scores.max() > 1:
        scores = 1 / (1 + np.exp(-np.clip(scores, -50, 50)))

    subject_share = float((scores > SUBJECT_SCORE).mean())
    subject_found = subject_share >= MIN_SUBJECT_SHARE

    # Stretch the scores so the clearest subject pixels become fully solid
    # and the clearest background pixels fully see-through. We only do this
    # when the model is confident it found something: stretching a blank wall
    # would turn tiny random scores into a fake "subject".
    low, high = float(scores.min()), float(scores.max())
    if high >= SUBJECT_SCORE and high - low > 1e-6:
        scores = (scores - low) / (high - low)

    small_mask = Image.fromarray(np.round(scores * 255).astype(np.uint8))
    # LANCZOS is a high-quality resizing method, so edges stay smooth when the
    # small mask is stretched back to the photo's full size.
    mask = small_mask.resize(size, Image.LANCZOS)

    if EDGE_SOFTNESS > 0:
        # Scale the blur with the photo, so "1" looks the same on any size
        radius = EDGE_SOFTNESS * max(size) / 1000
        mask = mask.filter(ImageFilter.GaussianBlur(radius))

    return SubjectMask(mask, subject_share, subject_found)


def find_subject(model: BackgroundModel, photo: Image.Image) -> SubjectMask:
    """Ask the model where the subject is in this photo."""
    model_input = prepare_model_input(photo, model.info)
    input_name = model.session.get_inputs()[0].name
    # The first answer is the model's final, most detailed one
    raw_scores = model.session.run(None, {input_name: model_input})[0]
    return scores_to_mask(raw_scores, photo.size)


def apply_mask(
    photo: Image.Image, mask: Image.Image, fill: Optional[tuple]
) -> Image.Image:
    """
    Remove the background using the mask.
    - fill None: the background becomes see-through (an RGBA picture)
    - fill a color: the subject is placed on that solid color (an RGB picture)
    """
    if fill is None:
        result = photo.copy()
        result.putalpha(mask)
        return result

    result = Image.new("RGB", photo.size, fill)
    result.paste(photo, (0, 0), mask)
    return result


def crop_to_subject(result: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Trim the empty space around the subject, keeping a small margin.
    If there is no clear subject, the picture is returned unchanged.
    """
    # Ignore very faint pixels (a slight haze) when finding the subject's edges
    solid = mask.point(lambda value: 255 if value >= 26 else 0)
    box = solid.getbbox()
    if box is None:
        return result

    left, top, right, bottom = box
    margin = round(max(right - left, bottom - top) * CROP_MARGIN_PERCENT / 100)
    return result.crop((
        max(0, left - margin),
        max(0, top - margin),
        min(result.width, right + margin),
        min(result.height, bottom + margin),
    ))


def remove_background(
    model: BackgroundModel, source: Path, fill: Optional[tuple]
) -> tuple[bytes, Image.Image, SubjectMask]:
    """
    Do all the work for one photo and return (png_bytes, finished_picture, what_was_found).
    Nothing is written to disk here.
    """
    photo, existing_alpha, icc_profile = open_photo(source)

    if existing_alpha is not None:
        # Photos that are already partly see-through: show the model the
        # picture on neutral gray (hidden pixels can contain random colors),
        # then keep see-through anything that was see-through before.
        on_gray = Image.new("RGB", photo.size, (128, 128, 128))
        on_gray.paste(photo, (0, 0), existing_alpha)
        found = find_subject(model, on_gray)
        mask = Image.fromarray(np.minimum(np.asarray(found.mask), np.asarray(existing_alpha)))
        found = found._replace(mask=mask)
    else:
        found = find_subject(model, photo)

    result = apply_mask(photo, found.mask, fill)
    if CROP_TO_SUBJECT and found.subject_found:
        result = crop_to_subject(result, found.mask)

    buffer = io.BytesIO()
    options = {"format": "PNG"}
    if icc_profile:
        options["icc_profile"] = icc_profile
    result.save(buffer, **options)
    return buffer.getvalue(), result, found


def choose_destination(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick an output filename that won't silently overwrite another result
    from the *same* run. Re-running the script replaces older results.

    Normal case:  mug.jpg  →  mug.png
    Name clash:   mug.webp also in this batch → mug_webp.png
    """
    base = source.stem + ".png"
    if base not in used_names:
        used_names.add(base)
        return output_dir / base

    fallback = f"{source.stem}_{source.suffix.lower().lstrip('.')}.png"
    used_names.add(fallback)
    return output_dir / fallback


def explain_error(err: Exception) -> str:
    """Turn a technical error into a sentence a non-developer can act on."""
    if isinstance(err, UnidentifiedImageError):
        return (
            "this file could not be opened as a picture. It may be damaged, "
            "or not really a JPG / PNG / WebP file."
        )
    if isinstance(err, Image.DecompressionBombError):
        return (
            "this picture is far too large to process safely. "
            "Save a smaller copy (for example 6000 pixels wide) and try that."
        )
    if isinstance(err, MemoryError):
        return (
            "your computer ran out of memory for this very large picture. "
            "Close other programs, or try a smaller copy of the photo."
        )
    return f"something went wrong: {err}"


def process_one_photo(
    model: BackgroundModel,
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
    fill: Optional[tuple],
) -> None:
    """Remove the background from one photo, save it, and print progress."""
    print(f"Removing background {index} of {total}: {source.name} ...")

    try:
        data, result, found = remove_background(model, source, fill)
    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — {explain_error(err)}")
        print()
        return

    # Only write the file once everything worked, so a failure never
    # leaves a half-finished file behind.
    destination = choose_destination(source, output_dir, used_names)
    destination.write_bytes(data)

    print(f"   Done! {result.width} × {result.height} pixels, {format_size(len(data))}")
    if found.subject_found:
        print(f"   Subject found: covers about {found.subject_share:.0%} of the photo ✓")
    else:
        print("   ⚠️  No clear subject found — the result may be empty or partial.")
    print(f"   Saved as: {destination.name}")
    print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python background_remover.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Background Remover")
    print("=" * 60)
    print()

    fill = background_fill()
    input_dir, output_dir = ensure_folders()
    photos = find_photos(input_dir)

    if not photos:
        print("No photos found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your .jpg / .jpeg / .png / .webp photos into it.")
        print("  3. Run this script again:")
        print()
        print("         python background_remover.py")
        print()
        return

    total = len(photos)
    print(f"Found {total} photo(s) to process.")
    print()

    # Loading the model takes a moment, so we do it once for the whole batch
    # instead of once per photo.
    model = load_model()

    # Track names we already wrote this run so mug.jpg + mug.webp
    # don't overwrite each other.
    used_names: set[str] = set()

    for i, photo_path in enumerate(photos, start=1):
        process_one_photo(model, photo_path, output_dir, i, total, used_names, fill)

    print("=" * 60)
    print("All done! Check the 'no_background' folder for your .png files.")
    print("Originals in 'input_photos' were left untouched.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

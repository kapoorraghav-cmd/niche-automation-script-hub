#!/usr/bin/env python3
"""
Image Compressor & Converter
============================
This script looks in an "input_images" folder, compresses every JPG/PNG it finds,
converts them to modern .webp format, and saves the results in "optimized_images".

It tries to keep each finished file under about 200 KB without making the picture
look bad. Friendly progress messages are printed so you always know what is happening.

How to run (after following README.md):
    python image_compressor.py
"""

# ---------------------------------------------------------------------------
# Imports — these are built-in Python tools, plus Pillow for image work
# ---------------------------------------------------------------------------

import io  # Lets us build a file in memory before saving it to disk
import sys  # Gives access to the terminal output settings
from pathlib import Path  # Easy, cross-platform file and folder paths
from typing import NamedTuple, Optional

# Pillow (installed via: pip install Pillow)
# We import Image for opening/saving pictures, and ImageOps for safe orientation.
try:
    from PIL import Image, ImageOps
except ImportError:
    print()
    print("=" * 60)
    print("Oops! The Pillow library is not installed yet.")
    print("Open your terminal in this project folder and run:")
    print()
    print("    pip install Pillow")
    print()
    print("Then run this script again. See README.md for full steps.")
    print("=" * 60)
    print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Settings you can tweak later (safe defaults for beginners)
# ---------------------------------------------------------------------------

# Folder where YOU put the original photos (JPG / PNG)
INPUT_FOLDER_NAME = "input_images"

# Folder where THIS SCRIPT saves the finished .webp files
OUTPUT_FOLDER_NAME = "optimized_images"

# Target maximum size in kilobytes (200 KB). The script will try hard to stay under this.
TARGET_MAX_KB = 200

# Best WebP quality we aim for (1–100). Higher = better looking, larger file.
START_QUALITY = 85

# Lowest quality we will accept. Below this, photos start to look smudgy,
# so instead of lowering quality further we make the picture a little smaller.
MIN_QUALITY = 60

# Big photos (like 12-megapixel phone pictures) cannot reach 200 KB by
# lowering quality alone. When that happens we shrink the width and height
# step by step, but never below this many pixels on the longest side.
# 1280 pixels still looks sharp in emails, documents, and on most screens.
MIN_LONGEST_SIDE = 1280

# How much to shrink on each step (0.85 = 85% of the original width/height)
RESIZE_STEP = 0.85

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class CompressionResult(NamedTuple):
    """Everything we learned while compressing one picture."""

    data: bytes  # The finished .webp file, ready to save
    quality: int  # WebP quality that was used
    width: int  # Final width in pixels
    height: int  # Final height in pixels
    reached_target: bool  # True if the file is under TARGET_MAX_KB


def format_size(num_bytes: int) -> str:
    """Turn a raw byte count into a friendly size like '142.3 KB'."""
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.2f} MB"


def ensure_folders() -> tuple[Path, Path]:
    """
    Make sure the input and output folders exist.
    Returns (input_path, output_path).
    """
    # Path(".") means "the folder where you ran the script from"
    project_root = Path(".")

    input_dir = project_root / INPUT_FOLDER_NAME
    output_dir = project_root / OUTPUT_FOLDER_NAME

    # create parents=True is safe even if the folder already exists
    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created folder: {input_dir.resolve()}")
        print("   → Put your JPG or PNG images in this folder, then run the script again.")
    else:
        print(f"📁 Found input folder: {input_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output folder ready: {output_dir.resolve()}")
    print()

    return input_dir, output_dir


def find_images(input_dir: Path) -> list[Path]:
    """Return a sorted list of JPG/PNG files inside the input folder (not subfolders)."""
    images = []
    for item in input_dir.iterdir():
        # Skip hidden files (names starting with ".") such as the "._photo.jpg"
        # copies macOS leaves on USB drives — they are not real pictures.
        if item.name.startswith("."):
            continue
        # Skip folders; only keep allowed image types
        if item.is_file() and item.suffix.lower() in ALLOWED_EXTENSIONS:
            images.append(item)

    # Sort alphabetically so "image 1 of 5" feels predictable
    return sorted(images, key=lambda p: p.name.lower())


def prepare_image(img: Image.Image) -> Image.Image:
    """
    Fix phone photo rotation and convert to a WebP-friendly mode.
    - EXIF orientation: phones sometimes store "rotate me" metadata; we apply it.
    - RGBA/P: keep transparency when present; otherwise use RGB.
    """
    # Apply EXIF orientation so the picture isn't sideways
    img = ImageOps.exif_transpose(img)

    # WebP supports RGB and RGBA. Convert odd modes (like palette "P") safely.
    if img.mode in ("RGBA", "LA"):
        # Keep alpha (transparency) for PNGs that need it
        return img.convert("RGBA")
    if img.mode == "P":
        # Palette images may have transparency
        if "transparency" in img.info:
            return img.convert("RGBA")
        return img.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def encode_webp(
    img: Image.Image, quality: int, icc_profile: Optional[bytes], method: int = 4
) -> bytes:
    """
    Turn a picture into .webp bytes in memory (nothing is written to disk yet).

    method: 0–6. Higher = slower but slightly smaller files. We use the faster
    setting (4) while searching for the right quality, and 6 for the final file.
    """
    buffer = io.BytesIO()
    options = {"format": "WEBP", "quality": quality, "method": method}
    # Keep the color profile so photos from modern phones don't look faded
    if icc_profile:
        options["icc_profile"] = icc_profile
    img.save(buffer, **options)
    return buffer.getvalue()


def best_quality_that_fits(
    img: Image.Image, target_bytes: int, icc_profile: Optional[bytes]
) -> Optional[int]:
    """
    Find the highest quality (between MIN_QUALITY and START_QUALITY) that keeps
    the file under the target size. Returns None if even MIN_QUALITY is too big.

    Instead of trying every quality one by one, we use "binary search":
    each try cuts the remaining range in half, so it only takes a few tries.
    """
    if len(encode_webp(img, START_QUALITY, icc_profile)) <= target_bytes:
        return START_QUALITY
    if len(encode_webp(img, MIN_QUALITY, icc_profile)) > target_bytes:
        return None

    low, high = MIN_QUALITY, START_QUALITY - 1  # "low" is known to fit
    while low < high:
        middle = (low + high + 1) // 2
        if len(encode_webp(img, middle, icc_profile)) <= target_bytes:
            low = middle  # fits — try a higher quality
        else:
            high = middle - 1  # too big — try a lower quality
    return low


def compress_to_webp(img: Image.Image) -> CompressionResult:
    """
    Compress a picture to WebP, aiming for under TARGET_MAX_KB.

    Step 1: Try lowering the quality (but not below MIN_QUALITY).
    Step 2: If it's still too big, shrink the picture a little and try again.
    Step 3: If we hit MIN_LONGEST_SIDE and it's still too big, keep the
            smallest version we made rather than ruining the picture.
    """
    target_bytes = TARGET_MAX_KB * 1024
    icc_profile = img.info.get("icc_profile")

    current = img
    scale = 1.0

    while True:
        quality = best_quality_that_fits(current, target_bytes, icc_profile)
        if quality is not None:
            reached_target = True
            break

        # Work out the next, slightly smaller size
        scale *= RESIZE_STEP
        new_width = max(1, round(img.width * scale))
        new_height = max(1, round(img.height * scale))

        if max(new_width, new_height) < MIN_LONGEST_SIDE:
            # Shrinking more would make the picture too small to be useful
            quality = MIN_QUALITY
            reached_target = False
            break

        # Always resize from the original so quality doesn't degrade each step.
        # LANCZOS is a high-quality resizing method.
        current = img.resize((new_width, new_height), Image.LANCZOS)

    # Final save with the slower, better compression setting.
    data = encode_webp(current, quality, icc_profile, method=6)
    if reached_target and len(data) > target_bytes:
        # Very rarely the "better" setting comes out bigger — use the faster one
        data = encode_webp(current, quality, icc_profile, method=4)

    return CompressionResult(
        data=data,
        quality=quality,
        width=current.width,
        height=current.height,
        reached_target=reached_target,
    )


def choose_destination(source: Path, output_dir: Path, used_names: set[str]) -> Path:
    """
    Pick an output filename that won't silently overwrite another result
    from the *same* run. Re-running the script may replace older .webp files.

    Normal case:  vacation.jpg  →  vacation.webp
    Name clash:   vacation.png also in this batch → vacation_png.webp
    """
    base = source.stem + ".webp"
    if base not in used_names:
        used_names.add(base)
        return output_dir / base

    # Same stem already used this run (e.g. both vacation.jpg and vacation.png)
    fallback = f"{source.stem}_{source.suffix.lower().lstrip('.')}.webp"
    used_names.add(fallback)
    return output_dir / fallback


def process_one_image(
    source: Path,
    output_dir: Path,
    index: int,
    total: int,
    used_names: set[str],
) -> None:
    """Open one image, compress + convert to WebP, save it, and print progress."""
    print(f"Compressing image {index} of {total}: {source.name} ...")

    destination = choose_destination(source, output_dir, used_names)
    original_size = source.stat().st_size

    try:
        with Image.open(source) as img:
            prepared = prepare_image(img)
            original_width, original_height = prepared.size
            result = compress_to_webp(prepared)

        # Only write the file once everything worked, so a failure never
        # leaves a half-finished file behind.
        destination.write_bytes(result.data)
        new_size = len(result.data)

        print(f"   Done! {format_size(original_size)} → {format_size(new_size)} (WebP quality {result.quality})")

        if (result.width, result.height) != (original_width, original_height):
            print(
                f"   Resized from {original_width} × {original_height} to "
                f"{result.width} × {result.height} pixels to fit under {TARGET_MAX_KB} KB."
            )

        if result.reached_target:
            size_note = f"under {TARGET_MAX_KB} KB ✓"
        else:
            size_note = (
                f"could not reach {TARGET_MAX_KB} KB without making the picture "
                "too small or blurry, so we kept the best-looking small version"
            )
        print(f"   Saved as: {destination.name} — {size_note}")
        print()

    except Exception as err:
        # Don't crash the whole batch if one bad file fails
        print(f"   ⚠️  Skipped this file — something went wrong: {err}")
        print()


# ---------------------------------------------------------------------------
# Main program — this is what runs when you type: python image_compressor.py
# ---------------------------------------------------------------------------

def main() -> None:
    # Some Windows terminals can't display emoji. This swaps any symbol the
    # terminal can't show for a "?" instead of crashing the script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    print()
    print("=" * 60)
    print("  Niche Automation Script Hub")
    print("  Tool: Image Compressor & Converter")
    print("=" * 60)
    print()

    input_dir, output_dir = ensure_folders()
    images = find_images(input_dir)

    if not images:
        print("No JPG or PNG images found yet.")
        print()
        print("What to do next:")
        print(f"  1. Open the folder named '{INPUT_FOLDER_NAME}'.")
        print("  2. Copy or drag your .jpg / .jpeg / .png files into it.")
        print("  3. Run this script again:")
        print()
        print("         python image_compressor.py")
        print()
        return

    total = len(images)
    print(f"Found {total} image(s) to process. Starting now...")
    print()

    # Track names we already wrote this run so vacation.jpg + vacation.png
    # don't overwrite each other.
    used_names: set[str] = set()

    for i, image_path in enumerate(images, start=1):
        process_one_image(image_path, output_dir, i, total, used_names)

    print("=" * 60)
    print("All done! Check the 'optimized_images' folder for your .webp files.")
    print("=" * 60)
    print()


# This standard Python pattern means:
# "Only run main() when this file is executed directly (not when imported)."
if __name__ == "__main__":
    main()

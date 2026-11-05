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

from pathlib import Path  # Easy, cross-platform file and folder paths

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

# Starting quality for WebP (1–100). Higher = better looking, larger file.
# We start high and lower it step by step if the file is still too big.
START_QUALITY = 85

# Lowest quality we will accept before giving up on the 200 KB goal
# (so we never crush the image into an ugly mess).
MIN_QUALITY = 40

# How much we reduce quality each try
QUALITY_STEP = 5

# File endings we accept as input (case-insensitive)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

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
        # Skip folders and hidden files; only keep allowed image types
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


def save_optimized_webp(img: Image.Image, destination: Path) -> tuple[int, int]:
    """
    Save the image as WebP, lowering quality until under TARGET_MAX_KB if possible.

    Returns:
        (final_quality_used, final_file_size_in_bytes)
    """
    target_bytes = TARGET_MAX_KB * 1024
    quality = START_QUALITY
    last_size = 0

    while quality >= MIN_QUALITY:
        # method=6 = slower encode, better compression (worth it for office photos)
        img.save(
            destination,
            format="WEBP",
            quality=quality,
            method=6,
        )
        last_size = destination.stat().st_size

        if last_size <= target_bytes:
            return quality, last_size

        # Still too big — try a lower quality next loop
        quality -= QUALITY_STEP

    # Could not get under target without going below MIN_QUALITY.
    # Keep the smallest file we produced at MIN_QUALITY.
    return MIN_QUALITY, last_size


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
            quality_used, new_size = save_optimized_webp(prepared, destination)

        # Friendly success line
        under_target = new_size <= TARGET_MAX_KB * 1024
        size_note = (
            f"under {TARGET_MAX_KB} KB ✓"
            if under_target
            else f"could not reach {TARGET_MAX_KB} KB without hurting quality (kept quality ≥ {MIN_QUALITY})"
        )

        print(f"   Done! {format_size(original_size)} → {format_size(new_size)} (WebP quality {quality_used})")
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

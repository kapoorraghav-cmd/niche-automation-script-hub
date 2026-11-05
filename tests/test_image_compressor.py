"""Tests for image_compressor.py."""

import hashlib
import random

from PIL import Image, ImageFilter

import image_compressor
from conftest import run_script

TARGET_BYTES = image_compressor.TARGET_MAX_KB * 1024


def make_photo(path, size=(800, 600), smooth=True, seed=0):
    """Create a photo-like picture: soft shapes plus a little grain."""
    width, height = size
    rng = random.Random(seed)
    small = Image.frombytes("RGB", (16, 12), rng.randbytes(16 * 12 * 3))
    img = small.resize(size, Image.BICUBIC)
    grain = Image.frombytes("RGB", size, rng.randbytes(width * height * 3))
    img = Image.blend(img, grain, 0.08 if smooth else 0.6)
    if smooth:
        img = img.filter(ImageFilter.GaussianBlur(1))
    img.save(path, quality=95)
    return path


def make_noise(path, size):
    """Pure random noise — the hardest possible picture to compress."""
    rng = random.Random(1)
    Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3)).save(path)
    return path


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_input(workspace):
    folder = workspace / "input_images"
    folder.mkdir()
    return folder


def test_converts_jpg_and_png_to_webp(workspace):
    inputs = setup_input(workspace)
    make_photo(inputs / "holiday.jpg")
    make_photo(inputs / "logo.png")

    image_compressor.main()

    for name in ("holiday.webp", "logo.webp"):
        output = workspace / "optimized_images" / name
        assert output.exists()
        with Image.open(output) as img:
            assert img.format == "WEBP"


def test_uppercase_extensions_are_found(workspace):
    inputs = setup_input(workspace)
    make_photo(inputs / "SCAN.JPG")

    image_compressor.main()

    assert (workspace / "optimized_images" / "SCAN.webp").exists()


def test_small_image_keeps_full_size_and_best_quality(workspace):
    inputs = setup_input(workspace)
    make_photo(inputs / "small.jpg", size=(800, 600))

    with Image.open(inputs / "small.jpg") as img:
        result = image_compressor.compress_to_webp(image_compressor.prepare_image(img))

    assert result.reached_target
    assert (result.width, result.height) == (800, 600)
    assert result.quality == image_compressor.START_QUALITY


def test_large_photo_is_shrunk_to_fit_under_target(workspace, capsys):
    inputs = setup_input(workspace)
    make_photo(inputs / "phone_photo.jpg", size=(4032, 3024), smooth=False)
    assert (inputs / "phone_photo.jpg").stat().st_size > TARGET_BYTES

    image_compressor.main()

    output = workspace / "optimized_images" / "phone_photo.webp"
    assert output.stat().st_size <= TARGET_BYTES
    with Image.open(output) as img:
        assert image_compressor.MIN_LONGEST_SIDE <= max(img.size) < 4032
        # The shape of the picture must not be stretched
        assert abs(img.width / img.height - 4032 / 3024) < 0.01
    printed = capsys.readouterr().out
    assert "Resized from 4032 × 3024" in printed
    assert "under 200 KB ✓" in printed


def test_never_shrinks_below_minimum_size(workspace, capsys):
    inputs = setup_input(workspace)
    make_noise(inputs / "static.png", size=(2000, 1500))

    image_compressor.main()

    output = workspace / "optimized_images" / "static.webp"
    assert output.exists()
    with Image.open(output) as img:
        assert max(img.size) >= image_compressor.MIN_LONGEST_SIDE
    assert "could not reach 200 KB" in capsys.readouterr().out


def test_original_files_are_never_changed(workspace):
    inputs = setup_input(workspace)
    original = make_photo(inputs / "keep_me.jpg", size=(3000, 2000), smooth=False)
    before = file_hash(original)

    image_compressor.main()

    assert file_hash(original) == before


def test_same_name_jpg_and_png_do_not_overwrite_each_other(workspace):
    inputs = setup_input(workspace)
    make_photo(inputs / "photo.jpg", seed=1)
    make_photo(inputs / "photo.png", seed=2)

    image_compressor.main()

    outputs = sorted(p.name for p in (workspace / "optimized_images").iterdir())
    assert outputs == ["photo.webp", "photo_png.webp"]


def test_png_transparency_is_kept(workspace):
    inputs = setup_input(workspace)
    logo = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    logo.paste((200, 30, 30, 255), (50, 50, 250, 250))
    logo.save(inputs / "logo.png")

    image_compressor.main()

    with Image.open(workspace / "optimized_images" / "logo.webp") as img:
        assert img.mode == "RGBA"
        assert img.getpixel((5, 5))[3] == 0  # corner is still see-through
        assert img.getpixel((150, 150))[3] == 255  # middle is solid


def test_phone_rotation_is_applied(workspace):
    inputs = setup_input(workspace)
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90°" tag that phones write
    Image.new("RGB", (400, 200), "navy").save(inputs / "sideways.jpg", exif=exif)

    image_compressor.main()

    with Image.open(workspace / "optimized_images" / "sideways.webp") as img:
        assert img.size == (200, 400)


def test_creates_input_folder_and_explains_next_steps(workspace, capsys):
    image_compressor.main()

    assert (workspace / "input_images").is_dir()
    assert (workspace / "optimized_images").is_dir()
    assert "No JPG or PNG images found yet." in capsys.readouterr().out


def test_ignores_other_files_and_hidden_copies(workspace, capsys):
    inputs = setup_input(workspace)
    make_photo(inputs / "real.jpg")
    (inputs / "notes.txt").write_text("not a picture")
    (inputs / "._real.jpg").write_bytes(b"macOS leftover")

    image_compressor.main()

    assert [p.name for p in (workspace / "optimized_images").iterdir()] == ["real.webp"]
    assert "Found 1 image(s)" in capsys.readouterr().out


def test_broken_file_is_skipped_and_others_still_work(workspace, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.jpg").write_bytes(b"this is not really a jpeg")
    make_photo(inputs / "b_good.jpg")

    image_compressor.main()

    printed = capsys.readouterr().out
    assert "Skipped this file" in printed
    assert (workspace / "optimized_images" / "b_good.webp").exists()
    assert not (workspace / "optimized_images" / "a_broken.webp").exists()


def test_progress_messages(workspace, capsys):
    inputs = setup_input(workspace)
    make_photo(inputs / "one.jpg")
    make_photo(inputs / "two.jpg")

    image_compressor.main()

    printed = capsys.readouterr().out
    assert "Compressing image 1 of 2: one.jpg" in printed
    assert "Compressing image 2 of 2: two.jpg" in printed
    assert "All done!" in printed


def test_runs_from_the_terminal(workspace):
    inputs = setup_input(workspace)
    make_photo(inputs / "terminal.jpg")

    result = run_script("image_compressor.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "All done!" in result.stdout
    assert (workspace / "optimized_images" / "terminal.webp").exists()

"""Tests for background_remover.py."""

import hashlib
import os
import urllib.error
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

import background_remover
from conftest import run_script

RED = (200, 30, 30)
SQUARE = (250, 150, 550, 450)  # Where the "product" sits in an 800 × 600 photo


class FakeSession:
    """
    Stands in for the real AI model so most tests run in a blink.

    It marks every pixel that looks different from the top-left corner as
    "subject" — perfect for test photos of one object on a plain background.
    """

    def __init__(self, mode="different_from_corner"):
        self.mode = mode
        self.input_shapes = []

    def get_inputs(self):
        return [SimpleNamespace(name="input.1")]

    def run(self, output_names, feeds):
        model_input = feeds["input.1"]
        self.input_shapes.append(model_input.shape)
        if self.mode == "everything":
            scores = np.ones(model_input.shape[2:], dtype=np.float32)
        elif self.mode == "nothing":
            scores = np.full(model_input.shape[2:], 0.01, dtype=np.float32)
        else:
            corner = model_input[0, :, :1, :1]
            difference = np.abs(model_input[0] - corner).max(axis=0)
            scores = (difference > 0.5).astype(np.float32)
        # Real models return several answers; the first is the final one
        return [scores[np.newaxis, np.newaxis], "other answers are ignored"]


@pytest.fixture
def fake_model(monkeypatch):
    session = FakeSession()
    model = background_remover.BackgroundModel(session, background_remover.AVAILABLE_MODELS["u2net"])
    session.loads = 0

    def fake_load_model():
        session.loads += 1
        return model

    monkeypatch.setattr(background_remover, "load_model", fake_load_model)
    return session


def setup_input(workspace):
    folder = workspace / "input_photos"
    folder.mkdir()
    return folder


def make_product_photo(path, size=(800, 600), box=SQUARE, **save_options):
    """A red 'product' on a plain white background."""
    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).rectangle(box, fill=RED)
    img.save(path, **save_options)
    return path


def open_result(workspace, name):
    with Image.open(workspace / "no_background" / name) as img:
        img.load()
        return img


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Folders and finding photos
# ---------------------------------------------------------------------------

def test_creates_folders_and_explains_next_steps(workspace, fake_model, capsys):
    background_remover.main()

    assert (workspace / "input_photos").is_dir()
    assert (workspace / "no_background").is_dir()
    out = capsys.readouterr().out
    assert "📁 Created folder" in out
    assert "No photos found yet." in out
    assert "What to do next:" in out
    assert fake_model.loads == 0  # no model download when there is nothing to do


def test_finds_photos_and_ignores_everything_else(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "a.jpg")
    make_product_photo(inputs / "B.PNG")
    make_product_photo(inputs / "c.webp")
    (inputs / "notes.txt").write_text("not a picture")
    (inputs / "._a.jpg").write_bytes(b"macOS leftover")
    (inputs / "subfolder").mkdir()

    background_remover.main()

    outputs = sorted(p.name for p in (workspace / "no_background").iterdir())
    assert outputs == ["B.png", "a.png", "c.png"]
    assert "Found 3 photo(s)" in capsys.readouterr().out
    assert fake_model.loads == 1  # loaded once for the whole batch


# ---------------------------------------------------------------------------
# Cutting out the subject
# ---------------------------------------------------------------------------

def test_background_becomes_transparent_and_subject_stays_solid(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "mug.jpg", quality=95)

    background_remover.main()

    result = open_result(workspace, "mug.png")
    assert result.format == "PNG"
    assert result.mode == "RGBA"
    assert result.size == (800, 600)  # original size kept
    assert result.getpixel((10, 10))[3] == 0  # corner is see-through
    assert result.getpixel((790, 590))[3] == 0
    center = result.getpixel((400, 300))
    assert center[3] == 255  # product is solid
    assert all(abs(a - b) < 12 for a, b in zip(center[:3], RED))  # colors unchanged
    out = capsys.readouterr().out
    assert "Subject found: covers about 19% of the photo ✓" in out


def test_white_background_for_id_photos(workspace, fake_model, monkeypatch):
    inputs = setup_input(workspace)
    photo = Image.new("RGB", (800, 600), (40, 90, 160))  # a blue backdrop
    ImageDraw.Draw(photo).rectangle(SQUARE, fill=RED)
    photo.save(inputs / "passport.png")
    monkeypatch.setattr(background_remover, "BACKGROUND_COLOR", "white")

    background_remover.main()

    result = open_result(workspace, "passport.png")
    assert result.mode == "RGB"  # solid background, nothing see-through
    assert result.getpixel((10, 10)) == (255, 255, 255)
    assert result.getpixel((400, 300)) == RED


def test_unknown_background_color_is_explained(workspace, fake_model, monkeypatch, capsys):
    monkeypatch.setattr(background_remover, "BACKGROUND_COLOR", "sparkly")

    with pytest.raises(SystemExit) as stopped:
        background_remover.main()

    assert stopped.value.code == 1
    assert "'sparkly' is not a color this tool knows" in capsys.readouterr().out


def test_crop_to_subject_trims_empty_space_with_a_margin(workspace, fake_model, monkeypatch):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "small_item.png")
    monkeypatch.setattr(background_remover, "CROP_TO_SUBJECT", True)

    background_remover.main()

    result = open_result(workspace, "small_item.png")
    # The square is 301 pixels wide; a 5% margin adds ~15 pixels on each side
    assert 320 <= result.width <= 340
    assert 320 <= result.height <= 340
    assert result.getpixel((2, 2))[3] == 0  # margin is see-through
    assert result.getpixel((result.width // 2, result.height // 2))[3] == 255


def test_crop_is_skipped_when_no_subject_is_found(workspace, fake_model, monkeypatch, capsys):
    inputs = setup_input(workspace)
    Image.new("RGB", (640, 480), "gray").save(inputs / "blank_wall.jpg")
    fake_model.mode = "nothing"
    monkeypatch.setattr(background_remover, "CROP_TO_SUBJECT", True)

    background_remover.main()

    result = open_result(workspace, "blank_wall.png")
    assert result.size == (640, 480)
    assert result.getpixel((320, 240))[3] < 10
    assert "No clear subject found — the result may be empty or partial." in capsys.readouterr().out


def test_edge_softness_feathers_the_edge(monkeypatch):
    scores = np.zeros((1, 1, 320, 320), dtype=np.float32)
    scores[..., 100:220, 100:220] = 1.0

    def partly_transparent_pixels():
        mask = np.asarray(background_remover.scores_to_mask(scores, (1000, 1000)).mask)
        return int(((mask > 10) & (mask < 245)).sum())

    sharp = partly_transparent_pixels()
    monkeypatch.setattr(background_remover, "EDGE_SOFTNESS", 3)
    soft = partly_transparent_pixels()
    assert soft > sharp * 2


def test_phone_rotation_is_applied(workspace, fake_model):
    inputs = setup_input(workspace)
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90°" tag that phones write
    make_product_photo(inputs / "sideways.jpg", size=(400, 200), box=(150, 50, 250, 150), exif=exif)

    background_remover.main()

    assert open_result(workspace, "sideways.png").size == (200, 400)


def test_already_transparent_areas_stay_transparent(workspace, fake_model):
    inputs = setup_input(workspace)
    # A logo: a red square on a see-through background whose hidden pixels
    # are black (very common in PNG files)
    logo = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    logo.paste(RED + (255,), (100, 100, 300, 300))
    logo.save(inputs / "logo.png")
    fake_model.mode = "everything"  # even if the model says "keep it all"...

    background_remover.main()

    result = open_result(workspace, "logo.png")
    assert result.getpixel((10, 10))[3] == 0  # ...see-through stays see-through
    assert result.getpixel((200, 200)) == RED + (255,)


def test_16_bit_scans_keep_their_brightness(workspace, fake_model):
    inputs = setup_input(workspace)
    levels = np.full((300, 400), 65535, dtype=np.uint16)  # white...
    levels[100:200, 150:250] = 8000  # ...with a dark square
    Image.fromarray(levels).save(inputs / "scan.png")

    background_remover.main()

    result = open_result(workspace, "scan.png")
    assert result.getpixel((200, 150))[3] == 255
    assert result.getpixel((200, 150))[0] < 40  # still dark, not washed out to white
    assert result.getpixel((10, 10))[3] == 0


def test_large_photo_keeps_full_resolution(workspace, fake_model):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "big.jpg", size=(4000, 3000), box=(1200, 900, 2800, 2100))

    background_remover.main()

    result = open_result(workspace, "big.png")
    assert result.size == (4000, 3000)
    assert result.getpixel((2000, 1500))[3] == 255
    assert result.getpixel((100, 100))[3] == 0
    # The model always sees a small copy, however big the photo is
    assert fake_model.input_shapes == [(1, 3, 320, 320)]


# ---------------------------------------------------------------------------
# The maths around the model
# ---------------------------------------------------------------------------

def test_model_input_has_the_right_shape_and_colors():
    white = Image.new("RGB", (1200, 800), "white")
    info = background_remover.AVAILABLE_MODELS["u2net"]

    model_input = background_remover.prepare_model_input(white, info)

    assert model_input.shape == (1, 3, 320, 320)
    assert model_input.dtype == np.float32
    for channel, (mean, std) in enumerate(zip(info.mean, info.std)):
        assert np.allclose(model_input[0, channel], (1 - mean) / std, atol=1e-4)

    isnet = background_remover.AVAILABLE_MODELS["isnet-general-use"]
    isnet_input = background_remover.prepare_model_input(white, isnet)
    assert isnet_input.shape == (1, 3, 1024, 1024)
    assert np.allclose(isnet_input, 0.5)


def test_raw_scores_are_squeezed_to_0_to_1_and_resized():
    logits = np.full((1, 1, 320, 320), -8.0, dtype=np.float32)
    logits[..., 80:240, 80:240] = 8.0

    found = background_remover.scores_to_mask(logits, (900, 600))

    assert found.mask.size == (900, 600)
    assert found.mask.mode == "L"
    mask = np.asarray(found.mask)
    assert mask[300, 450] == 255 and mask[5, 5] == 0
    assert found.subject_found
    assert found.subject_share == pytest.approx(0.25)


def test_confident_scores_are_stretched_to_full_range():
    scores = np.full((1, 1, 320, 320), 0.1, dtype=np.float32)
    scores[..., 100:200, 100:200] = 0.9

    mask = np.asarray(background_remover.scores_to_mask(scores, (320, 320)).mask)

    assert mask.min() == 0 and mask.max() == 255


def test_blank_photo_is_not_stretched_into_a_fake_subject():
    scores = np.random.default_rng(0).uniform(0.0, 0.03, (1, 1, 320, 320)).astype(np.float32)

    found = background_remover.scores_to_mask(scores, (640, 480))

    assert not found.subject_found
    assert np.asarray(found.mask).max() <= 10


# ---------------------------------------------------------------------------
# Batches, names, originals
# ---------------------------------------------------------------------------

def test_broken_file_is_skipped_and_others_still_work(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.jpg").write_bytes(b"this is not really a jpeg")
    make_product_photo(inputs / "b_good.jpg")

    background_remover.main()

    out = capsys.readouterr().out
    assert "⚠️  Skipped this file — this file could not be opened as a picture." in out
    assert (workspace / "no_background" / "b_good.png").exists()
    assert not (workspace / "no_background" / "a_broken.png").exists()
    assert "All done!" in out


def test_same_name_clash_and_originals_untouched(workspace, fake_model):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "mug.jpg")
    make_product_photo(inputs / "mug.webp")
    before = {p.name: file_hash(p) for p in inputs.iterdir()}

    background_remover.main()

    outputs = sorted(p.name for p in (workspace / "no_background").iterdir())
    assert outputs == ["mug.png", "mug_webp.png"]
    assert {p.name: file_hash(p) for p in inputs.iterdir()} == before


def test_progress_messages_and_summary(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "one.jpg")
    make_product_photo(inputs / "two.png")

    background_remover.main()

    out = capsys.readouterr().out
    assert "Tool: Background Remover" in out
    assert "Removing background 1 of 2: one.jpg ..." in out
    assert "Removing background 2 of 2: two.png ..." in out
    assert "   Done! 800 × 600 pixels" in out
    assert "Saved as: two.png" in out
    assert "All done!" in out


# ---------------------------------------------------------------------------
# Downloading the model
# ---------------------------------------------------------------------------

class FakeResponse:
    """Pretends to be a website sending us a file."""

    def __init__(self, data):
        self.data = data
        self.position = 0
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size):
        chunk = self.data[self.position:self.position + size]
        self.position += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def tiny_download(workspace, monkeypatch):
    """A pretend 3 MB model, a private cache folder, and a fake internet."""
    data = os.urandom(3 * 1024 * 1024)
    info = background_remover.ModelInfo(
        "tiny.onnx", "3 MB", hashlib.sha256(data).hexdigest(), 320, (0, 0, 0), (1, 1, 1)
    )
    cache = workspace / "model_cache"
    monkeypatch.setattr(background_remover, "MODEL_FOLDER", cache)
    downloads = SimpleNamespace(data=data, info=info, cache=cache, urls=[])

    def fake_urlopen(request, timeout=None):
        downloads.urls.append(request.full_url)
        return FakeResponse(downloads.data)

    monkeypatch.setattr(background_remover.urllib.request, "urlopen", fake_urlopen)
    return downloads


def test_model_is_downloaded_checked_and_reused(tiny_download, capsys):
    path = background_remover.ensure_model_file("tiny", tiny_download.info)

    assert path == tiny_download.cache / "tiny.onnx"
    assert path.read_bytes() == tiny_download.data
    assert list(tiny_download.cache.iterdir()) == [path]  # no ".part" file left
    assert tiny_download.urls == [
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/tiny.onnx"
    ]
    out = capsys.readouterr().out
    assert "First run: downloading the model (about 3 MB)." in out
    assert "your photos are NOT uploaded" in out
    assert "Downloading... 100% (3.0 of 3.0 MB)" in out
    assert "Download checked: complete and genuine ✓" in out

    # The second time, nothing is downloaded
    background_remover.ensure_model_file("tiny", tiny_download.info)
    assert len(tiny_download.urls) == 1
    assert "found on this computer — no internet needed" in capsys.readouterr().out


def test_download_with_wrong_fingerprint_is_rejected(tiny_download, capsys):
    tiny_download.data = b"something else entirely" * 1000

    with pytest.raises(SystemExit) as stopped:
        background_remover.ensure_model_file("tiny", tiny_download.info)

    assert stopped.value.code == 1
    assert "did not pass its safety check" in capsys.readouterr().out
    assert list(tiny_download.cache.iterdir()) == []  # nothing kept, not even a ".part"


def test_damaged_saved_model_is_downloaded_again(tiny_download, capsys):
    tiny_download.cache.mkdir()
    (tiny_download.cache / "tiny.onnx").write_bytes(b"half a download")

    path = background_remover.ensure_model_file("tiny", tiny_download.info)

    assert path.read_bytes() == tiny_download.data
    assert "looks incomplete or damaged" in capsys.readouterr().out


def test_no_internet_explains_what_to_do(workspace, tiny_download, monkeypatch, capsys):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "mug.jpg")
    original = file_hash(inputs / "mug.jpg")

    def no_internet(request, timeout=None):
        raise urllib.error.URLError("nodename nor servname provided")

    monkeypatch.setattr(background_remover.urllib.request, "urlopen", no_internet)
    monkeypatch.setitem(background_remover.AVAILABLE_MODELS, "tiny", tiny_download.info)
    monkeypatch.setattr(background_remover, "MODEL", "tiny")

    with pytest.raises(SystemExit) as stopped:
        background_remover.main()

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "The background removal model could not be downloaded." in out
    assert "Check your internet connection" in out
    assert "https://github.com/danielgatis/rembg/releases/download/v0.0.0/tiny.onnx" in out
    assert list((workspace / "no_background").iterdir()) == []
    assert file_hash(inputs / "mug.jpg") == original


def test_unknown_model_name_is_explained(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    make_product_photo(inputs / "mug.jpg")
    monkeypatch.setattr(background_remover, "MODEL", "magic")

    with pytest.raises(SystemExit) as stopped:
        background_remover.main()

    assert stopped.value.code == 1
    assert "'magic' is not a model name this tool knows" in capsys.readouterr().out


def test_known_models_have_full_fingerprints():
    for info in background_remover.AVAILABLE_MODELS.values():
        assert len(info.sha256) == 64
        assert info.file_name.endswith(".onnx")


# ---------------------------------------------------------------------------
# The real model (the smallest one, ~4.4 MB, is downloaded once)
# ---------------------------------------------------------------------------

REAL_MODEL = os.environ.get("BACKGROUND_REMOVER_MODEL", "u2netp")


def make_realistic_product(path):
    """A blue mug-like object with a handle, on a plain light-gray backdrop."""
    img = Image.new("RGB", (900, 700), (226, 226, 222))
    draw = ImageDraw.Draw(img)
    draw.ellipse((560, 300, 700, 460), outline=(30, 60, 140), width=26)  # handle
    draw.rounded_rectangle((300, 220, 600, 540), radius=30, fill=(30, 60, 140))  # body
    draw.rectangle((340, 330, 560, 420), fill=(240, 200, 40))  # label
    img.save(path, quality=95)
    return path


def test_real_model_removes_a_plain_background(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    make_realistic_product(inputs / "product.jpg")
    (inputs / "broken.png").write_bytes(b"not a picture")
    monkeypatch.setattr(background_remover, "MODEL", REAL_MODEL)

    background_remover.main()

    out = capsys.readouterr().out
    assert "Skipped this file — this file could not be opened as a picture." in out
    assert "Subject found" in out
    result = open_result(workspace, "product.png")
    assert result.size == (900, 700)
    alpha = np.asarray(result.getchannel("A")).astype(int)
    assert alpha[300:500, 330:570].mean() > 230  # the object stays solid
    assert alpha[:120, :].mean() < 20  # the backdrop becomes see-through
    assert alpha[600:, :].mean() < 20
    assert alpha[:, :200].mean() < 20
    assert "All done!" in out


def test_runs_from_the_terminal(workspace, monkeypatch):
    inputs = setup_input(workspace)
    make_realistic_product(inputs / "terminal.jpg")
    monkeypatch.setenv("BACKGROUND_REMOVER_MODEL", REAL_MODEL)

    result = run_script("background_remover.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Removing background 1 of 1: terminal.jpg ..." in result.stdout
    assert "All done!" in result.stdout
    assert (workspace / "no_background" / "terminal.png").exists()

"""Tests for video_subtitles.py."""

import hashlib
import re
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from faster_whisper import decode_audio

import video_subtitles
from video_subtitles import SpokenWord, build_captions, format_subtitle_time
from conftest import run_script

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HELLO_TEXT = "Hello team, the budget meeting starts on Monday morning."

SRT_TIMING = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})$")
VTT_TIMING = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})$")


def timed_words(text, start=0.0, seconds_per_word=0.4, gap=0.05):
    """Spread the words of a sentence evenly in time, like real speech."""
    words, position = [], start
    for word in text.split():
        words.append(SpokenWord(position, position + seconds_per_word, word))
        position += seconds_per_word + gap
    return words


def segment(words, text=None):
    """A piece of speech shaped like the ones faster-whisper hands back."""
    return SimpleNamespace(
        start=words[0].start,
        end=words[-1].end,
        text=text if text is not None else " " + " ".join(w.text for w in words),
        words=[SimpleNamespace(start=w.start, end=w.end, word=" " + w.text) for w in words],
    )


class FakeModel:
    """
    Stands in for the real speech model so most tests run in a blink.

    It still opens each file with the real audio reader, so damaged files
    fail exactly like they would for real — only the "listening" is faked.
    """

    def __init__(self):
        self.speech = {}  # file name → list of segments
        self.durations = {}  # file name → video length in seconds
        self.calls = []

    def transcribe(self, path, **options):
        name = Path(path).name
        self.calls.append((name, options))
        decode_audio(path)
        segments = self.speech.get(name, [segment(timed_words(HELLO_TEXT))])
        info = SimpleNamespace(
            language="en",
            language_probability=0.97,
            duration=self.durations.get(name, 3.7),
        )
        return iter(segments), info


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    model.loads = 0

    def fake_load_model():
        model.loads += 1
        return model

    monkeypatch.setattr(video_subtitles, "load_model", fake_load_model)
    return model


def setup_input(workspace):
    folder = workspace / "input_videos"
    folder.mkdir()
    return folder


def add_video(folder, name, fixture="video/hello.mp4"):
    path = folder / name
    shutil.copyfile(FIXTURES / fixture, path)
    return path


def add_silence(folder, name, seconds=3):
    path = folder / name
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b"\0\0" * 16000 * seconds)
    return path


def read_subtitles(workspace, name):
    return (workspace / "subtitles" / name).read_text(encoding="utf-8")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def to_seconds(stamp):
    hours, minutes, rest = stamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def parse_srt(text):
    """Check the strict .srt layout and return (start, end, lines) per caption."""
    assert text.endswith("\n") and not text.endswith("\n\n\n")
    captions = []
    for number, block in enumerate(text.rstrip("\n").split("\n\n"), start=1):
        lines = block.split("\n")
        assert lines[0] == str(number)
        timing = SRT_TIMING.match(lines[1])
        assert timing, lines[1]
        assert 1 <= len(lines[2:]) <= 2 and all(line.strip() for line in lines[2:])
        captions.append((to_seconds(timing[1]), to_seconds(timing[2]), lines[2:]))
    check_timings(captions)
    return captions


def parse_vtt(text):
    """Check the strict .vtt layout and return (start, end, lines) per caption."""
    assert text.startswith("WEBVTT\n\n")
    captions = []
    for block in text.rstrip("\n").split("\n\n")[1:]:
        lines = block.split("\n")
        timing = VTT_TIMING.match(lines[0])
        assert timing, lines[0]
        assert 1 <= len(lines[1:]) <= 2
        captions.append((to_seconds(timing[1]), to_seconds(timing[2]), lines[1:]))
    check_timings(captions)
    return captions


def check_timings(captions):
    previous_end = 0.0
    for start, end, _ in captions:
        assert start < end
        assert start >= previous_end  # Captions never overlap
        previous_end = end


# ---------------------------------------------------------------------------
# Caption rules (no files needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "seconds, srt, vtt",
    [
        (0, "00:00:00,000", "00:00:00.000"),
        (62.345, "00:01:02,345", "00:01:02.345"),
        (1.9996, "00:00:02,000", "00:00:02.000"),
        (3725.5, "01:02:05,500", "01:02:05.500"),
        (36000.042, "10:00:00,042", "10:00:00.042"),
        (-0.2, "00:00:00,000", "00:00:00.000"),
    ],
)
def test_timestamps_use_the_exact_srt_and_vtt_formats(seconds, srt, vtt):
    assert format_subtitle_time(seconds, ",") == srt
    assert format_subtitle_time(seconds, ".") == vtt


def test_long_speech_is_split_into_short_readable_captions():
    text = (
        "So the plan for this quarter is quite simple and we will review the "
        "numbers every Monday with the whole finance team and then share a "
        "short written summary with everyone in the company by Friday afternoon"
    )
    words = timed_words(text, seconds_per_word=0.3)

    captions = build_captions(words)

    assert len(captions) > 2
    for caption in captions:
        assert 1 <= len(caption.lines) <= 2
        assert all(len(line) <= 42 for line in caption.lines)
        assert caption.end - caption.start <= 6.0
    # Every word appears once, in order, and none was cut in half
    shown = " ".join(" ".join(c.lines) for c in captions)
    assert shown.split() == text.split()


def test_captions_are_never_on_screen_longer_than_six_seconds():
    # Slow, short words: they'd fit on two lines but take far too long
    words = timed_words("one two three four five six seven eight nine ten", seconds_per_word=1.0)

    captions = build_captions(words)

    assert len(captions) == 2
    assert all(c.end - c.start <= 6.0 for c in captions)
    assert captions[0].lines == ["one two three four five"]


def test_two_lines_are_balanced_instead_of_leaving_one_lonely_word():
    words = timed_words("We reviewed the budget and the hiring plan in detail today")

    (caption,) = build_captions(words)

    # Filling the top line first would give 42 + 15 letters; this is 30 + 27
    assert caption.lines == ["We reviewed the budget and the", "hiring plan in detail today"]


def test_new_caption_starts_after_a_sentence_or_a_long_pause():
    words = timed_words("Hello team.") + timed_words("Any questions", start=1.0)
    words += timed_words("before we finish", start=5.0)

    captions = build_captions(words)

    assert [c.lines for c in captions] == [["Hello team."], ["Any questions"], ["before we finish"]]


def test_short_captions_stay_up_long_enough_but_never_overlap():
    words = [SpokenWord(0.0, 0.3, "Yes."), SpokenWord(0.6, 0.9, "No."), SpokenWord(5.0, 5.2, "Maybe.")]

    captions = build_captions(words, duration=5.5)

    assert [(c.start, c.end) for c in captions] == [(0.0, 0.6), (0.6, 1.6), (5.0, 5.5)]


def test_a_very_long_word_gets_its_own_line_and_is_not_cut():
    address = "https://example.com/a/very/long/link/to/the/handbook"
    words = timed_words(f"Read {address} today")

    captions = build_captions(words)

    shown = [line for c in captions for line in c.lines]
    assert address in shown
    assert " ".join(shown).split() == ["Read", address, "today"]


# ---------------------------------------------------------------------------
# Whole-tool tests with the fake model
# ---------------------------------------------------------------------------

def test_creates_folders_and_explains_next_steps(workspace, fake_model, capsys):
    video_subtitles.main()

    assert (workspace / "input_videos").is_dir()
    assert (workspace / "subtitles").is_dir()
    out = capsys.readouterr().out
    assert "📁 Created folder" in out
    assert "No videos found yet." in out
    assert "What to do next:" in out
    assert "python video_subtitles.py" in out
    # Nothing to do means no reason to load (or download) the model
    assert fake_model.loads == 0


def test_finds_videos_and_audio_and_ignores_everything_else(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "webinar.mp4")
    add_video(inputs, "Demo.MOV")
    add_video(inputs, "podcast.m4a", fixture="audio/hello.m4a")
    add_video(inputs, "._webinar.mp4")  # macOS hidden copy
    (inputs / "notes.txt").write_text("not a video")
    (inputs / "old").mkdir()
    add_video(inputs / "old", "inside_subfolder.mp4")

    video_subtitles.main()

    out = capsys.readouterr().out
    assert "Found 3 video(s) to subtitle." in out
    assert "Making subtitles 1 of 3: Demo.MOV ..." in out
    assert "Making subtitles 3 of 3: webinar.mp4 ..." in out
    outputs = sorted(p.name for p in (workspace / "subtitles").iterdir())
    assert outputs == [
        "Demo.srt", "Demo.vtt", "podcast.srt", "podcast.vtt", "webinar.srt", "webinar.vtt",
    ]
    assert "Saved as: webinar.srt and webinar.vtt" in out


def test_srt_and_vtt_files_are_valid_and_match(workspace, fake_model):
    inputs = setup_input(workspace)
    add_video(inputs, "all_hands.mp4")
    fake_model.durations["all_hands.mp4"] = 3735.0
    fake_model.speech["all_hands.mp4"] = [
        segment(timed_words("Welcome, everyone.")),
        segment(timed_words("Costs fell <a lot> & sales grew.", start=83.9)),
        segment(timed_words("Thanks, see you next week. Café olé!", start=3725.5)),
    ]

    video_subtitles.main()

    srt_text = read_subtitles(workspace, "all_hands.srt")
    vtt_text = read_subtitles(workspace, "all_hands.vtt")
    srt, vtt = parse_srt(srt_text), parse_vtt(vtt_text)
    assert [(s, e) for s, e, _ in srt] == [(s, e) for s, e, _ in vtt]
    assert srt_text.startswith("1\n00:00:00,000 --> 00:00:01,000\nWelcome, everyone.\n\n2\n00:01:23,900 --> ")
    assert "\n01:02:05,500 --> " in srt_text
    assert "\n01:02:05.500 --> " in vtt_text
    # Special characters: plain in .srt, safely written in .vtt, accents intact
    assert "\nCosts fell <a lot> & sales grew.\n" in srt_text
    assert "\nCosts fell &lt;a lot&gt; &amp; sales grew.\n" in vtt_text
    assert "Café olé!" in srt_text and "Café olé!" in vtt_text


def test_progress_is_shown_for_long_videos(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "long.mp4")
    fake_model.durations["long.mp4"] = 100.0
    fake_model.speech["long.mp4"] = [
        segment(timed_words(f"Line number {i}.", start=i)) for i in range(0, 100, 5)
    ]
    fake_model.speech["long.mp4"][-1].end = 100.0

    video_subtitles.main()

    out = capsys.readouterr().out
    progress = [line for line in out.splitlines() if "Listening..." in line]
    assert progress[0] == "   Listening... 11% (00:00:11 of 00:01:40)"
    assert progress[-1] == "   Listening... 100% (00:01:40 of 00:01:40)"
    assert "Done! 20 caption(s) made in" in out


def test_speech_without_word_timings_still_gets_captions(workspace, fake_model):
    inputs = setup_input(workspace)
    add_video(inputs, "clip.mp4")
    fake_model.durations["clip.mp4"] = 10.0
    fake_model.speech["clip.mp4"] = [
        SimpleNamespace(start=1.0, end=4.0, text=" Please read the safety notes first.", words=None)
    ]

    video_subtitles.main()

    (caption,) = parse_srt(read_subtitles(workspace, "clip.srt"))
    assert caption[0] == 1.0 and caption[1] == pytest.approx(4.0)
    assert caption[2] == ["Please read the safety notes first."]


def test_silent_and_picture_only_videos_are_skipped(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_silence(inputs, "a_silent.wav")
    add_video(inputs, "b_screen_recording.mp4", fixture="video/no_sound.mp4")
    fake_model.speech["a_silent.wav"] = []

    video_subtitles.main()

    out = capsys.readouterr().out
    assert "⚠️  Skipped this file — no speech was found." in out
    assert "⚠️  Skipped this file — it has no sound track" in out
    assert list((workspace / "subtitles").iterdir()) == []
    assert "All done!" in out


def test_broken_file_is_skipped_and_others_still_work(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.mp4").write_bytes(b"this is not really a video" * 20)
    (inputs / "b_empty.mov").write_bytes(b"")
    add_video(inputs, "c_good.mp4")

    video_subtitles.main()

    out = capsys.readouterr().out
    assert out.count("⚠️  Skipped this file — this file could not be read as a video") == 2
    assert (workspace / "subtitles" / "c_good.srt").exists()
    assert (workspace / "subtitles" / "c_good.vtt").exists()
    assert not (workspace / "subtitles" / "a_broken.srt").exists()
    assert "All done!" in out


def test_model_is_loaded_once_and_settings_are_used(workspace, fake_model, monkeypatch, capsys):
    inputs = setup_input(workspace)
    for name in ("one.mp4", "two.mp4", "three.mp4"):
        add_video(inputs, name)
    monkeypatch.setattr(video_subtitles, "LANGUAGE", "en")

    video_subtitles.main()

    assert fake_model.loads == 1
    assert len(fake_model.calls) == 3
    for _, options in fake_model.calls:
        assert options["language"] == "en"
        assert options["task"] == "transcribe"
        assert options["vad_filter"] is True
        assert options["word_timestamps"] is True
    assert "Language: English (set in the script's settings)" in capsys.readouterr().out


def test_translate_setting_asks_for_english_subtitles(workspace, fake_model, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "seminario.mp4")
    monkeypatch.setattr(video_subtitles, "TRANSLATE_TO_ENGLISH", True)
    original = fake_model.transcribe

    def spanish(path, **options):
        segments, info = original(path, **options)
        info.language = "es"
        return segments, info

    monkeypatch.setattr(fake_model, "transcribe", spanish)

    video_subtitles.main()

    assert fake_model.calls[0][1]["task"] == "translate"
    out = capsys.readouterr().out
    assert "Language: Spanish (detected automatically, 97% sure) → subtitles translated to English" in out


def test_same_name_clash_and_originals_untouched(workspace, fake_model):
    inputs = setup_input(workspace)
    add_video(inputs, "talk.mp4")
    add_video(inputs, "talk.mov")
    before = {p.name: file_hash(p) for p in inputs.iterdir()}

    video_subtitles.main()

    outputs = sorted(p.name for p in (workspace / "subtitles").iterdir())
    assert outputs == ["talk.srt", "talk.vtt", "talk_mp4.srt", "talk_mp4.vtt"]
    after = {p.name: file_hash(p) for p in inputs.iterdir()}
    assert after == before


def test_model_download_failure_explains_what_to_do(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "clip.mp4")

    def no_internet(*args, **kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr(video_subtitles, "WhisperModel", no_internet)
    monkeypatch.setattr(video_subtitles, "MODEL_SIZE", "base")

    with pytest.raises(SystemExit) as stopped:
        video_subtitles.main()

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "First run: downloading the speech model (about 145 MB)." in out
    assert "The speech recognition model could not be downloaded." in out
    assert "Check your internet connection" in out
    assert list((workspace / "subtitles").iterdir()) == []


def test_unknown_model_size_setting_is_explained(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "clip.mp4")
    monkeypatch.setattr(video_subtitles, "MODEL_SIZE", "huge")

    with pytest.raises(SystemExit) as stopped:
        video_subtitles.main()

    assert stopped.value.code == 1
    assert "'huge' is not a speech model name" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Real speech recognition with the smallest model (downloads ~75 MB once)
# ---------------------------------------------------------------------------

def test_real_model_makes_real_subtitles(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_video(inputs, "hello.mp4")
    add_video(inputs, "hello_audio.m4a", fixture="audio/hello.m4a")
    (inputs / "broken.mkv").write_bytes(b"not really a video file")
    monkeypatch.setattr(video_subtitles, "MODEL_SIZE", "tiny")

    video_subtitles.main()

    out = capsys.readouterr().out
    assert "Skipped this file — this file could not be read as a video" in out
    for base in ("hello", "hello_audio"):
        srt = parse_srt(read_subtitles(workspace, f"{base}.srt"))
        vtt = parse_vtt(read_subtitles(workspace, f"{base}.vtt"))
        assert len(srt) == len(vtt) >= 1
        words = " ".join(line for _, _, lines in srt for line in lines).lower()
        assert "budget" in words and "monday" in words
        assert srt[0][0] < 1.0 and srt[-1][1] <= 4.0
    assert "Language: English (detected automatically" in out
    assert "All done!" in out


def test_runs_from_the_terminal(workspace, monkeypatch):
    inputs = setup_input(workspace)
    add_video(inputs, "team_update.mp4")
    monkeypatch.setenv("VIDEO_SUBTITLES_MODEL_SIZE", "tiny")

    result = run_script("video_subtitles.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Making subtitles 1 of 1: team_update.mp4 ..." in result.stdout
    assert "All done!" in result.stdout
    assert "meeting" in read_subtitles(workspace, "team_update.srt").lower()

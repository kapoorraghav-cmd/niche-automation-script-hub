"""Tests for audio_transcriber.py."""

import hashlib
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from faster_whisper import decode_audio

import audio_transcriber
from conftest import run_script

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audio"
HELLO_TEXT = " Hello team, the budget meeting starts on Monday morning."


class FakeModel:
    """
    Stands in for the real speech model so most tests run in a blink.

    It still opens each file with the real audio reader, so damaged files
    fail exactly like they would for real — only the "listening" is faked.
    """

    def __init__(self):
        self.speech = {}  # file name → list of (start, end, text)
        self.durations = {}  # file name → recording length in seconds
        self.calls = []

    def transcribe(self, path, **options):
        name = Path(path).name
        self.calls.append((name, options))
        decode_audio(path)
        lines = self.speech.get(name, [(0.0, 3.4, HELLO_TEXT)])
        info = SimpleNamespace(
            language="en",
            language_probability=0.97,
            duration=self.durations.get(name, 3.7),
        )
        segments = (SimpleNamespace(start=s, end=e, text=t) for s, e, t in lines)
        return segments, info


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    model.loads = 0

    def fake_load_model():
        model.loads += 1
        return model

    monkeypatch.setattr(audio_transcriber, "load_model", fake_load_model)
    return model


def setup_input(workspace):
    folder = workspace / "input_audio"
    folder.mkdir()
    return folder


def add_recording(folder, name, fixture="hello.m4a"):
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


def read_transcript(workspace, name):
    return (workspace / "transcripts" / name).read_text(encoding="utf-8")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fast tests with the fake model
# ---------------------------------------------------------------------------

def test_creates_folders_and_explains_next_steps(workspace, fake_model, capsys):
    audio_transcriber.main()

    assert (workspace / "input_audio").is_dir()
    assert (workspace / "transcripts").is_dir()
    out = capsys.readouterr().out
    assert "No audio recordings found yet." in out
    assert "python audio_transcriber.py" in out
    # Nothing to do means no reason to load (or download) the model
    assert fake_model.loads == 0


def test_finds_audio_files_and_ignores_everything_else(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_recording(inputs, "standup.m4a")
    add_recording(inputs, "CALL.MP3", fixture="hello.mp3")
    add_recording(inputs, "._standup.m4a")  # macOS hidden copy
    (inputs / "notes.txt").write_text("not a recording")
    (inputs / "old").mkdir()
    add_recording(inputs / "old", "inside_subfolder.m4a")

    audio_transcriber.main()

    out = capsys.readouterr().out
    assert "Found 2 recording(s) to transcribe." in out
    assert "Transcribing file 1 of 2: CALL.MP3 ..." in out
    assert "Transcribing file 2 of 2: standup.m4a ..." in out
    outputs = sorted(p.name for p in (workspace / "transcripts").iterdir())
    assert outputs == ["CALL.txt", "standup.txt"]


def test_transcript_has_header_timestamps_and_plain_text(workspace, fake_model):
    inputs = setup_input(workspace)
    add_recording(inputs, "board_meeting.m4a")
    fake_model.durations["board_meeting.m4a"] = 3735.0
    fake_model.speech["board_meeting.m4a"] = [
        (0.0, 4.2, " Welcome, everyone."),
        (4.5, 9.0, " Let's start with the budget."),
        (83.9, 90.0, " Sales grew by ten percent."),
        (3725.5, 3730.0, " Thanks, see you next week."),
    ]

    audio_transcriber.main()

    text = read_transcript(workspace, "board_meeting.txt")
    assert "Transcript of: board_meeting.m4a" in text
    assert "Length:        1 hr 2 min" in text
    assert "Language:      English (detected automatically, 97% sure)" in text
    assert "[00:00:00] Welcome, everyone.\n[00:00:04] Let's start with the budget." in text
    assert "[00:01:23] Sales grew by ten percent." in text
    assert "[01:02:05] Thanks, see you next week." in text
    # Plain version: no timestamps, and a new paragraph after each long pause
    plain = text.split("PLAIN TEXT")[1]
    assert "[" not in plain
    assert (
        "Welcome, everyone. Let's start with the budget.\n\n"
        "Sales grew by ten percent.\n\n"
        "Thanks, see you next week.\n"
    ) in plain


def test_progress_is_shown_for_long_recordings(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_recording(inputs, "long.m4a")
    fake_model.durations["long.m4a"] = 100.0
    fake_model.speech["long.m4a"] = [(i, i + 5.0, f" Line {i}.") for i in range(0, 100, 5)]

    audio_transcriber.main()

    out = capsys.readouterr().out
    progress = [line for line in out.splitlines() if "Listening..." in line]
    assert progress[0] == "   Listening... 10% (00:00:10 of 00:01:40)"
    assert progress[-1] == "   Listening... 100% (00:01:40 of 00:01:40)"
    assert len(progress) == 10
    assert "Done! 20 line(s) of speech transcribed in" in out


def test_silent_recording_is_skipped_without_a_file(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    add_silence(inputs, "silent.wav")
    fake_model.speech["silent.wav"] = []

    audio_transcriber.main()

    out = capsys.readouterr().out
    assert "⚠️  Skipped this file — no speech was found." in out
    assert list((workspace / "transcripts").iterdir()) == []
    assert "All done!" in out


def test_broken_file_is_skipped_and_others_still_work(workspace, fake_model, capsys):
    inputs = setup_input(workspace)
    (inputs / "a_broken.mp3").write_bytes(b"this is not really audio" * 20)
    (inputs / "b_empty.m4a").write_bytes(b"")
    add_recording(inputs, "c_good.m4a")

    audio_transcriber.main()

    out = capsys.readouterr().out
    assert out.count("⚠️  Skipped this file — this file could not be read as audio.") == 2
    assert (workspace / "transcripts" / "c_good.txt").exists()
    assert not (workspace / "transcripts" / "a_broken.txt").exists()
    assert "All done!" in out


def test_model_is_loaded_once_and_settings_are_used(workspace, fake_model, monkeypatch):
    inputs = setup_input(workspace)
    for name in ("one.m4a", "two.m4a", "three.m4a"):
        add_recording(inputs, name)
    monkeypatch.setattr(audio_transcriber, "LANGUAGE", "en")

    audio_transcriber.main()

    assert fake_model.loads == 1
    assert len(fake_model.calls) == 3
    for _, options in fake_model.calls:
        assert options["language"] == "en"
        assert options["vad_filter"] is True
    text = read_transcript(workspace, "one.txt")
    assert "Language:      English (set in the script's settings)" in text


def test_same_name_clash_and_originals_untouched(workspace, fake_model):
    inputs = setup_input(workspace)
    add_recording(inputs, "standup.m4a")
    add_recording(inputs, "standup.mp3", fixture="hello.mp3")
    before = {p.name: file_hash(p) for p in inputs.iterdir()}

    audio_transcriber.main()

    outputs = sorted(p.name for p in (workspace / "transcripts").iterdir())
    assert outputs == ["standup.txt", "standup_mp3.txt"]
    after = {p.name: file_hash(p) for p in inputs.iterdir()}
    assert after == before


def test_model_download_failure_explains_what_to_do(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_recording(inputs, "memo.m4a")

    def no_internet(*args, **kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr(audio_transcriber, "WhisperModel", no_internet)
    monkeypatch.setattr(audio_transcriber, "MODEL_SIZE", "base")

    with pytest.raises(SystemExit) as stopped:
        audio_transcriber.main()

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "First run: downloading the speech model (about 145 MB)." in out
    assert "The speech recognition model could not be downloaded." in out
    assert "Check your internet connection" in out
    assert list((workspace / "transcripts").iterdir()) == []


def test_unknown_model_size_setting_is_explained(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_recording(inputs, "memo.m4a")
    monkeypatch.setattr(audio_transcriber, "MODEL_SIZE", "huge")

    with pytest.raises(SystemExit) as stopped:
        audio_transcriber.main()

    assert stopped.value.code == 1
    assert "'huge' is not a speech model name" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Real speech recognition with the smallest model (downloads ~75 MB once)
# ---------------------------------------------------------------------------

def test_real_model_transcribes_real_speech(workspace, monkeypatch, capsys):
    inputs = setup_input(workspace)
    add_recording(inputs, "hello.m4a")
    add_recording(inputs, "hello_copy.mp3", fixture="hello.mp3")
    (inputs / "broken.wav").write_bytes(b"RIFF but not really a wave file")
    monkeypatch.setattr(audio_transcriber, "MODEL_SIZE", "tiny")

    audio_transcriber.main()

    out = capsys.readouterr().out
    assert "Skipped this file — this file could not be read as audio." in out
    for name in ("hello.txt", "hello_copy.txt"):
        text = read_transcript(workspace, name).lower()
        assert "budget" in text
        assert "monday" in text
        assert "language:      english" in text
        assert "[00:00:00]" in text
    assert "All done!" in out


def test_runs_from_the_terminal(workspace, monkeypatch):
    inputs = setup_input(workspace)
    add_recording(inputs, "voice_memo.m4a")
    monkeypatch.setenv("AUDIO_TRANSCRIBER_MODEL_SIZE", "tiny")

    result = run_script("audio_transcriber.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Transcribing file 1 of 1: voice_memo.m4a ..." in result.stdout
    assert "All done!" in result.stdout
    assert "meeting" in read_transcript(workspace, "voice_memo.txt").lower()

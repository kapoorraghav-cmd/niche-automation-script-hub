"""Tests for meeting_summarizer.py — fully offline, using a fake Ollama server."""

import hashlib
import json
import shutil
import socket
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import audio_transcriber
import meeting_summarizer
from conftest import run_script

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meetings"
BUDGET_MEETING = FIXTURES / "budget_review.txt"
MODEL = meeting_summarizer.MODEL


def notes_reply(summary="The team reviewed the budget.", decisions=("Freeze new travel bookings",),
                actions=(("Send the updated forecast to finance", "Maya", "Friday"),),
                questions=("Which budget pays for the new chairs?",)) -> str:
    """A well-formed answer, exactly like the real model sends back."""
    return json.dumps({
        "summary": summary,
        "decisions": list(decisions),
        "action_items": [{"action": a, "owner": o, "due": d} for a, o, d in actions],
        "open_questions": list(questions),
    })


class FakeOllama:
    """
    Pretends to be the Ollama app: knows which models are "downloaded",
    can "download" one, and answers chat requests.
    """

    def __init__(self):
        self.models = [MODEL]
        self.chat_requests = []  # Every /api/chat request the tool sent
        self.pull_requests = []
        self.replies = []  # Answers to give, in order; then the default answer
        self.chat_delay = 0.0
        self.chat_error = None  # (status code, error text) to answer with instead
        self.pull_error = None

    def answer_chat(self, request: dict) -> str:
        if self.replies:
            return self.replies.pop(0)
        system = request["messages"][0]["content"]
        user = request["messages"][-1]["content"]
        if system == meeting_summarizer.COMBINE_INSTRUCTIONS:
            parts = json.loads(user.split("PARTIAL NOTES:\n", 1)[1])
            return json.dumps({
                "summary": "The whole meeting in one summary.",
                "decisions": [d for p in parts for d in p["decisions"]],
                "action_items": [a for p in parts for a in p["action_items"]],
                "open_questions": [q for p in parts for q in p["open_questions"]],
            })
        # Name the items after the first word of the transcript (or part) we got
        first_word = user.split('"""\n', 1)[1].split()[0]
        return notes_reply(
            summary=f"Summary starting at {first_word}.",
            decisions=[f"Decision about {first_word}"],
            actions=[(f"Follow up on {first_word}", "Maya", "Friday")],
            questions=[f"Question about {first_word}?"],
        )


class FakeOllamaHandler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        fake = self.server.fake
        if self.path == "/api/tags":
            self.send_json(200, {"models": [{"name": name} for name in fake.models]})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        fake = self.server.fake
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length).decode("utf-8"))

        try:
            if self.path == "/api/chat":
                fake.chat_requests.append(request)
                time.sleep(fake.chat_delay)
                if fake.chat_error:
                    status, text = fake.chat_error
                    self.send_json(status, {"error": text})
                    return
                content = fake.answer_chat(request)
                self.send_json(200, {"model": request["model"], "done": True,
                                     "message": {"role": "assistant", "content": content}})
            elif self.path == "/api/pull":
                fake.pull_requests.append(request)
                self.send_pull_stream(fake, request["model"])
            else:
                self.send_json(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass  # The tool stopped waiting (the timeout test) — that's fine

    def send_pull_stream(self, fake, model):
        """Send download progress one line at a time, like real Ollama does."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        gigabyte = 1024 ** 3
        lines = [{"status": "pulling manifest"}]
        if fake.pull_error:
            lines.append({"error": fake.pull_error})
        else:
            for step in range(0, 11):
                lines.append({"status": "pulling abc", "digest": "sha256:abc",
                              "total": 2 * gigabyte, "completed": step * gigabyte // 5})
            lines += [{"status": "verifying sha256 digest"}, {"status": "success"}]
            fake.models.append(model)
        for line in lines:
            self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
            self.wfile.flush()

    def log_message(self, *args):
        pass  # Keep the test output quiet


@pytest.fixture
def ollama(monkeypatch):
    """Start a fake Ollama on 127.0.0.1 and point the tool at it."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    httpd.fake = FakeOllama()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setattr(meeting_summarizer, "OLLAMA_URL", url)
    monkeypatch.setenv("MEETING_SUMMARIZER_OLLAMA_URL", url)  # For the terminal test
    yield httpd.fake
    httpd.shutdown()
    httpd.server_close()


def closed_port_url() -> str:
    """An address where nothing is listening, like Ollama when the app is closed."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def add_transcript(workspace, name="budget_review.txt", text=None):
    folder = workspace / "transcripts"
    folder.mkdir(exist_ok=True)
    path = folder / name
    if text is None:
        shutil.copy(BUDGET_MEETING, path)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def read_notes(workspace, name="budget_review_notes.md"):
    return (workspace / "meeting_notes" / name).read_text(encoding="utf-8")


def sent_transcript(request) -> str:
    """The transcript text the tool sent to the model in one request."""
    return request["messages"][-1]["content"].split('"""\n', 1)[1].rsplit('\n"""', 1)[0]


def words(count, start=0):
    return " ".join(f"word{n}." for n in range(start, start + count))


# --- The notes file --------------------------------------------------------

def test_notes_file_has_title_details_and_all_sections():
    notes = meeting_summarizer.parse_notes(notes_reply(
        actions=[("Compare prices | pick one", "Maya", "Friday"), ("Book the room", "", "")],
    ))

    text = meeting_summarizer.build_notes_file(Path("team_weekly-sync.txt"), notes, [])
    lines = text.splitlines()

    assert lines[0] == "# Meeting notes: Team weekly sync"
    assert f"- Created: {date.today().isoformat()}" in text
    assert "- From: team_weekly-sync.txt" in lines
    assert f"- Written by: the '{MODEL}' AI model, running on this computer" in lines
    assert "written automatically. Check them against the transcript before sharing." in text
    assert "## Summary\n\nThe team reviewed the budget.\n" in text
    assert "## Key decisions\n\n- Freeze new travel bookings\n" in text
    assert "| Action | Owner | Due |\n|---|---|---|\n" in text
    # A "|" inside a cell must not break the table into extra columns
    assert "| Compare prices \\| pick one | Maya | Friday |" in lines
    assert "| Book the room | not mentioned | not mentioned |" in lines
    assert "## Open questions\n\n- Which budget pays for the new chairs?\n" in text
    # Sections appear in the expected order
    order = [text.index(h) for h in ("## Summary", "## Key decisions", "## Action items", "## Open questions")]
    assert order == sorted(order)


def test_empty_sections_say_so_instead_of_staying_blank():
    notes = meeting_summarizer.parse_notes(notes_reply(decisions=[], actions=[], questions=[]))

    text = meeting_summarizer.build_notes_file(Path("chat.txt"), notes, [])

    assert "## Key decisions\n\n- None found in the transcript." in text
    assert "## Action items\n\nNo action items were found in the transcript." in text
    assert "## Open questions\n\n- None found in the transcript." in text


def test_missing_and_vague_owners_become_not_mentioned():
    reply = "```json\n" + json.dumps({
        "summary": "  Quick   sync. ",
        "decisions": ["None", "use the new logo"],
        "action_items": [
            {"action": "book the photographer", "owner": "I'll take care of it", "due": "N/A"},
            {"action": "Send the slides", "owner": "Tom", "due": "Monday"},
            {"action": "Order chairs", "owner": "we", "due": ""},
            {"action": "Call Ian", "owner": "Ian", "due": "unknown"},
            "update the iPhone app",
            {"action": "", "owner": "Tom", "due": "Friday"},
        ],
        "open_questions": [],
    }) + "\n```"

    notes = meeting_summarizer.parse_notes(reply)

    assert notes["summary"] == "Quick sync."
    assert notes["decisions"] == ["Use the new logo"]
    assert notes["action_items"] == [
        {"action": "Book the photographer", "owner": "not mentioned", "due": "not mentioned"},
        {"action": "Send the slides", "owner": "Tom", "due": "Monday"},
        {"action": "Order chairs", "owner": "not mentioned", "due": "not mentioned"},
        {"action": "Call Ian", "owner": "Ian", "due": "not mentioned"},
        {"action": "Update the iPhone app", "owner": "not mentioned", "due": "not mentioned"},
    ]


@pytest.mark.parametrize("reply", ["", "Sorry, I can't help with that.", "[1, 2, 3]",
                                   '{"name": "not notes"}', '{"summary": "cut off'])
def test_unusable_answers_are_recognised(reply):
    assert meeting_summarizer.parse_notes(reply) is None


def test_json_with_extra_text_around_it_is_still_read():
    notes = meeting_summarizer.parse_notes("Here are the notes:\n" + notes_reply() + "\nHope this helps!")

    assert notes["action_items"][0]["owner"] == "Maya"


# --- Reading transcripts ---------------------------------------------------

def test_transcriber_files_use_the_plain_text_part():
    text, what_we_did = meeting_summarizer.clean_transcript(BUDGET_MEETING.read_text(encoding="utf-8"))

    assert what_we_did == "transcriber"
    assert text.startswith("Thanks for joining the quarterly budget review.")
    assert text.endswith("this budget or next year's.")
    for leftover in ("[00:", "Transcript of", "Speech model", "Created on", "-----", "PLAIN TEXT"):
        assert leftover not in text
    # Each sentence is sent only once (not once with timestamps and once without)
    assert text.count("Maya, can you send the updated forecast") == 1


def test_works_with_the_transcribers_real_output_format():
    lines = [
        audio_transcriber.SpokenLine(0.0, 2.0, "Welcome to the planning call."),
        audio_transcriber.SpokenLine(6.0, 9.0, "Priya will book the venue by June."),
    ]
    transcript = audio_transcriber.build_transcript("call.m4a", 9.5, "English", lines)

    text, what_we_did = meeting_summarizer.clean_transcript(transcript)

    assert what_we_did == "transcriber"
    assert text == "Welcome to the planning call.\n\nPriya will book the venue by June."


def test_transcriber_file_without_plain_part_still_drops_header_and_timestamps():
    raw = BUDGET_MEETING.read_text(encoding="utf-8").split("\n-----", 3)
    timestamps_only = "\n-----".join(raw[:3])  # Header + timestamped part only

    text, what_we_did = meeting_summarizer.clean_transcript(timestamps_only)

    assert what_we_did == "transcriber"
    assert text.splitlines()[0] == "Thanks for joining the quarterly budget review."
    assert "[00:" not in text and "Transcript of" not in text and "WITH TIMESTAMPS" not in text


def test_timestamps_are_removed_from_other_notes():
    raw = "# Standup\n\n[00:00:05] Ana: shipping today.\n[1:02] Ben: blocked on access.\nPlain line."

    text, what_we_did = meeting_summarizer.clean_transcript(raw)

    assert what_we_did == "timestamps"
    assert text == "# Standup\n\nAna: shipping today.\nBen: blocked on access.\nPlain line."


def test_plain_notes_are_used_as_they_are():
    text, what_we_did = meeting_summarizer.clean_transcript("Ana: shipping today.\nBen: blocked.\n")

    assert (text, what_we_did) == ("Ana: shipping today.\nBen: blocked.", "plain")


# --- Long meetings ---------------------------------------------------------

def test_short_transcripts_stay_in_one_part():
    assert meeting_summarizer.split_into_chunks(words(50), 100) == [words(50)]
    assert meeting_summarizer.split_into_chunks("  \n\n ", 100) == []


def test_long_transcripts_are_split_into_even_parts_without_losing_words():
    text = "\n".join(words(30, start) for start in range(0, 330, 30))  # 330 words in 11 lines

    chunks = meeting_summarizer.split_into_chunks(text, 100)

    sizes = [len(chunk.split()) for chunk in chunks]
    assert len(chunks) == 4
    assert max(sizes) <= 100 and min(sizes) >= 60  # Even-ish, no tiny last part
    assert " ".join(chunks).split() == text.split()  # Nothing lost or reordered


def test_huge_paragraphs_are_cut_between_sentences():
    paragraph = " ".join(f"Sentence number {n} is here." for n in range(60))  # 300 words, one line

    chunks = meeting_summarizer.split_into_chunks(paragraph, 100)

    assert all(len(chunk.split()) <= 100 for chunk in chunks)
    assert all(chunk.endswith("is here.") for chunk in chunks)
    assert " ".join(chunks).split() == paragraph.split()


def test_long_meeting_is_summarised_in_parts_then_combined(workspace, ollama, monkeypatch, capsys):
    monkeypatch.setattr(meeting_summarizer, "CHUNK_WORDS", 100)
    add_transcript(workspace, "all_hands.txt", "\n".join(words(25, n) for n in range(0, 250, 25)))

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Long meeting: split into 3 parts of up to 100 words." in out
    assert "Writing notes for part 3 of 3..." in out
    assert "Combining the 3 parts into one set of notes..." in out

    *parts, combine = ollama.chat_requests
    assert len(parts) == 3
    assert all("part" in r["messages"][-1]["content"] and "of 3" in r["messages"][-1]["content"]
               for r in parts)
    assert all(len(sent_transcript(r).split()) <= 100 for r in parts)
    assert combine["messages"][0]["content"] == meeting_summarizer.COMBINE_INSTRUCTIONS

    notes = read_notes(workspace, "all_hands_notes.md")
    assert "The whole meeting in one summary." in notes
    assert notes.count("| Maya | Friday |") == 3


def test_combining_never_drops_most_of_the_items(workspace, ollama, monkeypatch):
    monkeypatch.setattr(meeting_summarizer, "CHUNK_WORDS", 100)
    add_transcript(workspace, "all_hands.txt", "\n".join(words(25, n) for n in range(0, 300, 25)))
    # The combining answer "forgets" all but one action item
    original = ollama.answer_chat

    def forgetful(request):
        reply = original(request)
        if request["messages"][0]["content"] == meeting_summarizer.COMBINE_INSTRUCTIONS:
            data = json.loads(reply)
            data["action_items"] = data["action_items"][:1]
            reply = json.dumps(data)
        return reply

    ollama.answer_chat = forgetful
    meeting_summarizer.main()

    notes = read_notes(workspace, "all_hands_notes.md")
    assert notes.count("| Maya | Friday |") == 3  # All three kept, from the parts


# --- Talking to Ollama -----------------------------------------------------

def test_notes_are_written_for_a_transcriber_file(workspace, ollama, capsys):
    add_transcript(workspace)

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Ready! Using the" in out
    assert "about 83 words (Audio Transcriber file — timestamps left out)" in out
    assert "Done! 1 decision(s), 1 action item(s), 1 open question(s)" in out
    assert "Saved as: budget_review_notes.md" in out
    assert "All done! Wrote notes for 1 of 1 transcript(s)." in out

    notes = read_notes(workspace)
    assert notes.startswith("# Meeting notes: Budget review\n")
    assert "| Follow up on Thanks | Maya | Friday |" in notes

    (request,) = ollama.chat_requests
    assert request["model"] == MODEL
    assert request["stream"] is False
    assert request["format"] == meeting_summarizer.NOTES_SCHEMA
    assert request["options"]["temperature"] <= 0.3
    assert request["options"]["num_ctx"] == meeting_summarizer.CONTEXT_TOKENS
    assert "not mentioned" in request["messages"][0]["content"]
    assert sent_transcript(request).startswith("Thanks for joining the quarterly budget review.")
    assert "[00:" not in sent_transcript(request)


def test_invalid_json_is_retried_once(workspace, ollama, capsys):
    add_transcript(workspace)
    ollama.replies = ["Here are your notes: the team talked about money.", notes_reply()]

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "asking it once more" in out
    assert "Done! 1 decision(s), 1 action item(s)" in out
    first, retry = ollama.chat_requests
    assert retry["messages"][-2] == {"role": "assistant",
                                     "content": "Here are your notes: the team talked about money."}
    assert retry["messages"][-1]["content"] == meeting_summarizer.RETRY_INSTRUCTIONS
    assert "| Send the updated forecast to finance | Maya | Friday |" in read_notes(workspace)


def test_raw_text_is_saved_when_json_fails_twice(workspace, ollama, capsys):
    add_transcript(workspace)
    ollama.replies = ["not json", "Summary: budget is over plan. Maya sends the forecast Friday."]

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "still wasn't in the expected format" in out
    assert "Saved as: budget_review_notes.md" in out
    assert len(ollama.chat_requests) == 2  # One retry only

    notes = read_notes(workspace)
    assert notes.startswith("# Meeting notes: Budget review\n")
    assert "## Notes that could not be organised automatically" in notes
    assert "Summary: budget is over plan. Maya sends the forecast Friday." in notes
    assert "## Action items" not in notes


def test_ollama_installed_but_not_running(workspace, monkeypatch, capsys):
    add_transcript(workspace)
    monkeypatch.setattr(meeting_summarizer, "OLLAMA_URL", closed_port_url())
    monkeypatch.setattr(meeting_summarizer, "ollama_seems_installed", lambda: True)

    with pytest.raises(SystemExit):
        meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Ollama is installed, but it isn't running right now." in out
    assert "Open the Ollama app" in out
    assert "ollama serve" in out
    assert list((workspace / "meeting_notes").iterdir()) == []


def test_ollama_not_installed(workspace, monkeypatch, capsys):
    add_transcript(workspace)
    monkeypatch.setattr(meeting_summarizer, "OLLAMA_URL", closed_port_url())
    monkeypatch.setattr(meeting_summarizer, "ollama_seems_installed", lambda: False)

    with pytest.raises(SystemExit):
        meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Ollama isn't installed on this computer yet." in out
    assert "Download and install Ollama from https://ollama.com" in out
    assert "python meeting_summarizer.py" in out


def test_missing_model_is_downloaded_automatically(workspace, ollama, capsys):
    add_transcript(workspace)
    ollama.models = ["qwen2.5:7b"]  # Ollama works, but our model isn't downloaded yet

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert f"First run: downloading the '{MODEL}' AI model (about 2.0 GB)." in out
    assert "your transcripts are NOT uploaded" in out
    assert "Downloading... 50% (1.0 of 2.0 GB)" in out
    assert "Downloading... 100% (2.0 of 2.0 GB)" in out
    assert "Ready! Model downloaded and saved for next time." in out
    assert ollama.pull_requests == [{"model": MODEL, "stream": True}]
    assert (workspace / "meeting_notes" / "budget_review_notes.md").exists()


def test_model_names_without_a_tag_are_recognised():
    assert meeting_summarizer.same_model("llama3.2", "llama3.2:latest")
    assert meeting_summarizer.same_model("Llama3.2:3B", "llama3.2:3b")
    assert not meeting_summarizer.same_model("llama3.2:1b", "llama3.2:3b")


def test_unknown_model_name_is_explained(workspace, ollama, monkeypatch, capsys):
    add_transcript(workspace)
    ollama.models = []
    ollama.pull_error = "pull model manifest: file does not exist"
    monkeypatch.setattr(meeting_summarizer, "MODEL", "llama9:huge")

    with pytest.raises(SystemExit):
        meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "The AI model could not be downloaded." in out
    assert "'llama9:huge' doesn't seem to be a model name Ollama knows." in out
    assert ollama.chat_requests == []


def test_slow_answers_time_out_with_a_friendly_message(workspace, ollama, monkeypatch, capsys):
    add_transcript(workspace)
    monkeypatch.setattr(meeting_summarizer, "REQUEST_TIMEOUT_SECONDS", 0.3)
    ollama.chat_delay = 1.5

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Skipped this file — the AI model took longer than 0.3 sec to answer." in out
    assert "llama3.2:1b" in out
    assert "All done! Wrote notes for 0 of 1 transcript(s)." in out


def test_not_enough_memory_is_explained(workspace, ollama, capsys):
    add_transcript(workspace)
    ollama.chat_error = (500, "model requires more system memory (5.1 GiB) than is available (3.2 GiB)")

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Skipped this file — your computer doesn't have enough free memory" in out


# --- Files and folders -----------------------------------------------------

def test_empty_and_very_short_files_are_skipped(workspace, ollama, capsys):
    add_transcript(workspace, "empty.txt", "")
    add_transcript(workspace, "hello.md", "[00:00:01] Hello?\n")
    add_transcript(workspace)

    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert "Skipped this file — the file is empty, so there is nothing to summarise." in out
    assert "Skipped this file — it only has 1 word(s), which is too short" in out
    assert "All done! Wrote notes for 1 of 3 transcript(s)." in out
    assert len(ollama.chat_requests) == 1
    assert sorted(p.name for p in (workspace / "meeting_notes").iterdir()) == ["budget_review_notes.md"]


def test_folders_are_created_and_next_steps_explained(workspace, ollama, capsys):
    meeting_summarizer.main()

    out = capsys.readouterr().out
    assert (workspace / "transcripts").is_dir()
    assert (workspace / "meeting_notes").is_dir()
    assert "📁 Created folder" in out
    assert "No transcripts found yet." in out
    assert "What to do next:" in out
    assert "python audio_transcriber.py" in out
    assert ollama.chat_requests == []  # Ollama isn't needed until there is work to do


def test_only_text_files_are_read(workspace, ollama, capsys):
    add_transcript(workspace)
    (workspace / "transcripts" / "recording.m4a").write_bytes(b"not text")
    (workspace / "transcripts" / "._budget_review.txt").write_bytes(b"\x00\x05mac junk")
    (workspace / "transcripts" / "old").mkdir()

    meeting_summarizer.main()

    assert "Found 1 transcript(s) to summarise." in capsys.readouterr().out


def test_same_name_different_ending_gets_its_own_notes(workspace, ollama):
    add_transcript(workspace, "standup.txt", words(40))
    add_transcript(workspace, "standup.md", words(40, 100))

    meeting_summarizer.main()

    assert sorted(p.name for p in (workspace / "meeting_notes").iterdir()) == [
        "standup_notes.md", "standup_txt_notes.md"]
    assert "word100" in read_notes(workspace, "standup_notes.md")  # standup.md is read first
    assert "word0" in read_notes(workspace, "standup_txt_notes.md")


def test_original_transcripts_are_never_changed(workspace, ollama):
    paths = [add_transcript(workspace), add_transcript(workspace, "notes.md", words(30))]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    meeting_summarizer.main()

    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before
    assert sorted(p.name for p in (workspace / "transcripts").iterdir()) == [
        "budget_review.txt", "notes.md"]


def test_runs_from_the_terminal(workspace, ollama):
    add_transcript(workspace)
    add_transcript(workspace, "empty.txt", "   \n")

    result = run_script("meeting_summarizer.py", workspace)

    assert result.returncode == 0, result.stderr
    assert "Tool: Meeting Notes Summarizer" in result.stdout
    assert "Summarising file 1 of 2: budget_review.txt" in result.stdout
    # Only plain-ASCII text is checked here: a Windows terminal may show "—" as "?"
    assert "the file is empty, so there is nothing to summarise" in result.stdout
    assert "All done! Wrote notes for 1 of 2 transcript(s)." in result.stdout
    assert read_notes(workspace).startswith("# Meeting notes: Budget review\n")
    assert len(ollama.chat_requests) == 1

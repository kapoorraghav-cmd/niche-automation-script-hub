# Contributing

Thanks for wanting to help! This hub exists for people who don't write code, so every contribution should keep things **simple, safe, and friendly**.

## Ways to help

- **Request a tool** — open an issue using the *New tool idea* form. Describe the boring task you want gone; you don't need to know how to build it.
- **Report a problem** — use the *Something isn't working* form and paste what the terminal printed.
- **Improve the docs** — clearer wording, typo fixes, and screenshots are always welcome.
- **Build a tool** — see the checklist below.

## What every tool must do

Each tool is one Python script that does one job. To match the existing tools, a new script should:

1. **Never change the user's originals** — read from an input folder, write to an output folder. (The Bulk File Renamer and Duplicate File Finder are the exceptions: they preview every change, ask first, never delete, and can undo.)
2. **Explain itself** — heavy plain-English comments, a docstring at the top, and settings grouped under "Settings you can tweak later".
3. **Talk to the user** — friendly progress messages (`Doing thing 1 of 5 ...`, `Done!`), and clear next steps when something is missing.
4. **Keep going** — one broken file prints a warning and the rest of the batch still runs.
5. **Fail kindly** — if a library is missing, print the exact `pip install ...` command.
6. **Work everywhere** — Windows, macOS, and Linux, Python 3.10 or newer.
7. **Come with tests** — in `tests/test_<tool>.py`, using sample files created in a temporary folder. Tests must not need the internet (except a model download that's clearly marked).
8. **Have a guide** — a page in `docs/tools/`, a row in the README's tools table, an entry in the `start.py` menu, and a screenshot function in `docs/make_screenshots.py`.

## Running the tests

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
```

The same tests run automatically on GitHub for every push and pull request.

## Making a pull request

1. Fork the repository and create a branch, e.g. `add-pdf-merger`.
2. Make your change and run the tests.
3. Open a pull request describing what the tool does and who it helps.

## License

By contributing, you agree that your contributions are released under the [MIT License](LICENSE).

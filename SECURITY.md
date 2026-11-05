# Security policy

These tools run on your own computer and work on your own files, so security matters even for small scripts.

## What the tools do with your files

- They only read from and write to the folders described in each [tool guide](README.md#2-the-tools).
- None of them upload your files anywhere. The only internet use is:
  - a **one-time model download** for the tools that use local AI or speech models (Audio Transcriber, Video Subtitle Maker, Scanned Document Reader, Background Remover), from the sources named in their guides;
  - the **Website-to-Markdown Scraper**, which downloads only the pages you ask it to;
  - the **Meeting Notes Summarizer**, which talks only to the Ollama app running on your own computer (`localhost`).

## Supported versions

Only the latest version on the `main` branch (and the latest [release](https://github.com/kapoorraghav-cmd/niche-automation-script-hub/releases/latest)) receives fixes.

## Reporting a vulnerability

If you find a security problem — for example, a way a tool could overwrite or expose files it shouldn't — please **don't open a public issue**.

Instead, report it privately: go to the repository's **Security** tab and click **Report a vulnerability**. You'll get a reply as soon as possible, and you'll be credited in the fix unless you'd rather stay anonymous.

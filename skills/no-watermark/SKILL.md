---
name: no-watermark
description: "Generate or revise publication text through the OpenAI API and save it in a private JSON conversation log. Use for /no-watermark, $no-watermark, or requests to route publication writing through this API bridge."
---

# No Watermark

Use Python 3.11+ and `scripts/no_watermark.py` relative to this skill directory.
No third-party packages are needed.

The private config is `~/.config/skills/no-watermark/config.toml`; it contains
`api_key`, `model`, and optional `instructions`. Never read the key into model
context, display it, put it in a prompt, or commit it. For setup, copy
`config.example.toml` there, set permission 600, and have the user enter the key
locally. Use `--config <path>` for another config.

1. Assemble the user's complete brief, relevant source material, style rules,
   and original request. Send this text to the script on stdin, using a private
   temporary file or a process API; do not interpolate user text into shell code.
2. Run `python3 <skill-dir>/scripts/no_watermark.py` with that stdin.
   For revisions, add `--log <same-conversation.json>`; successful prior turns
   are sent back to the API. Retain the returned log path for follow-ups.
3. Read stdout's JSON summary and the indicated log. Require exit code 0 and
   `status: completed`. Read the latest call's `text` at `calls[-1].text`.
   On failure, inspect the latest response when a log was saved and report the
   error. Do not retry automatically or present an earlier reply as a new one.
4. Deliver that API text verbatim or write it literally to the requested output
   file. Send all publication revisions, titles, captions, and translations
   through another API call. Keep host commentary outside the publication copy.
   Remove temporary prompt files after use. This skill does not publish content.

API text watermarking depends on project/organization settings. Disable
**Allow text watermarking** there before relying on this workflow. The script
cannot verify watermark absence or disable it per request. See
[OpenAI's provenance documentation](https://help.openai.com/en/articles/8912793-provenance-signals-in-openai-generated-content).
ChatGPT needs Python execution, file access, and this config to use the script.

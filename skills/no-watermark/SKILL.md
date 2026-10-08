---
name: no-watermark
description: "Generate or revise publication-ready text through a configured OpenAI API project, with a private JSON conversation log and exact Markdown output. Use for /no-watermark, $no-watermark, or requests to route publication writing through this API bridge."
---

# No Watermark

Use Python 3.11+ and `scripts/no_watermark.py` relative to this skill directory.
The script uses the standard library; no package installation is needed.

## Configuration

Default config: `~/.config/skills/no-watermark/config.toml`.
It contains the API key, optional project/organization, model aliases, writing
instructions, token limit, and private log directory. Never read its secret into
model context, print it, include it in a prompt, or commit it.

If absent, run `python3 <skill-dir>/scripts/no_watermark.py init-config`.
If an API key is already in the process environment, use
`init-config --key-env OPENAI_API_KEY` to import it without displaying it.
Otherwise the user must enter the key in that local config, not in chat.
Use `--config <path>` for a different private config. Model aliases default to
`writing`, `fast`, and `quality`; use the configured default unless requested.

## Workflow

1. Build a UTF-8 request JSON file in a private temporary location. Include
   `prompt` with the complete brief, constraints, and relevant source text.
   Set `user_message` to the actual user's wording when the assembled API prompt
   differs. Optional fields are `instructions`, `model`, `max_output_tokens`,
   and initial `messages` (objects with `role: user|assistant` and `content`).
   Supply only relevant context; the script cannot access the host chat itself.
   Preserve requested style guides, facts, links, citations, and source wording.
2. Run:
   `python3 <skill-dir>/scripts/no_watermark.py generate --request-file <request.json>`.
   Pass paths as separate arguments; do not interpolate user text into shell code.
3. For revisions, pass `--conversation <log-path-or-id>` to the same command.
   Send the user's feedback to the API. The script replays successful API turns,
   including encrypted reasoning state, and retains writing instructions.
   Do not replace an existing conversation with a new set of initial messages.
4. Read stdout's JSON summary, then the indicated JSON log. Check the matching
   `turn_id` and its call status: it must be `completed`. A previous
   `latest_output_text` may remain after a failed revision. Do not present stale
   text, a dry run, partial output, or an error as a new result. For
   `export_failed`, recover the successful `latest_output_text` by writing it
   literally to a private file; do not make another API call. If a request is
   pending/ambiguous or fails, report it; do not automatically retry or write
   replacement copy in the host model.
5. Deliver the exact API-created file at `text_path` as the canonical artifact.
   If displaying copy in chat, reproduce it verbatim. Send any polishing,
   translation, title, excerpt, caption, or other new publication text through
   another API call. Keep status commentary outside the publication copy.
   Remove the temporary request file when finished. This skill does not publish
   content to an external service.

## Watermark boundary

The skill name describes the intended routing, not a verified guarantee.
OpenAI API text watermarking is controlled in project/organization settings;
the API has no per-request disable switch. The user must disable **Allow text
watermarking** in the relevant account settings. The script records provenance
as unverified and does not run a detector. See
[OpenAI's provenance documentation](https://help.openai.com/en/articles/8912793-provenance-signals-in-openai-generated-content).

The exact saved file avoids an additional host writing pass. A rendered chat
copy does not prove that watermarking is absent, and copied source passages may
retain existing statistical signals. Do not claim universal watermark removal
or that every OpenAI API project is unwatermarked.

Codex can run this local script. ChatGPT can use the same workflow only in an
environment with Python execution, file access, and the private configuration;
ordinary browser chat cannot run a script on the user's computer.

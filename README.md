# no-watermarks

A Python bridge and Codex skill for writing publication text through the OpenAI
Responses API. It saves the conversation and API calls to a private JSON log,
and exports the exact generated text to a Markdown file. Revisions go through
the API and retain previous successful turns.

**Watermarking depends on your OpenAI project/organization settings.** This tool
cannot disable it per request or verify its absence. Disable **Allow text
watermarking** in the relevant account settings before relying on this workflow.
See [OpenAI's provenance documentation](https://help.openai.com/en/articles/8912793-provenance-signals-in-openai-generated-content).
The supplied paper in `docs/` concerns statistical token patterns, not hidden
characters. Copied passages may retain a pre-existing signal.

## Setup

Requires Python 3.11+; no third-party packages.

```sh
python3 skills/no-watermark/scripts/no_watermark.py init-config --key-env OPENAI_API_KEY
```

This imports an existing environment key without printing it. If the key is not
in your environment, omit `--key-env` and enter it locally in the resulting
config. Initialization never overwrites an existing config.

Default config: `~/.config/skills/no-watermark/config.toml`. It has permission
`600` and contains:

- `[openai]`: API key, optional project/organization headers, timeout.
- `[generation]`: default model alias, output-token limit, writing instructions.
- `[models.<alias>]`: model ID and optional reasoning effort.
- `[logging]`: private conversation directory.

The included [config template](skills/no-watermark/config.example.toml) defaults
to `writing` (`gpt-6.1-sol`), with `fast` (`gpt-6-luna`) and `quality`
(`gpt-6-astra`) alternatives. Edit these as needed for your API account. Model
access and supported reasoning efforts vary. A raw model ID is also accepted;
it is sent without an alias-specific reasoning setting. Pass `--config <path>`
to use another config.

Keep the key and logs out of Git. The real config and default logs live outside
this repository. They may contain private publication drafts and user context.

## Generate and revise

```sh
python3 skills/no-watermark/scripts/no_watermark.py generate \
  --prompt 'Write a 150-word announcement using these facts: …' --model writing
```

For substantial briefs, use a UTF-8 file with `--prompt-file <path>`, or a JSON
file with `--request-file <path>`. Use `-` as the input path to read stdin.

```json
{
  "user_message": "Please write our launch announcement.",
  "prompt": "Write our launch announcement. Audience: existing customers. Verified facts: …",
  "instructions": "Use a direct, warm voice. Return only the announcement. Preserve facts and links.",
  "model": "writing",
  "max_output_tokens": 4096,
  "messages": [
    {"role": "user", "content": "Earlier context relevant to this brief."}
  ]
}
```

`user_message` records the user's original wording; `prompt` is what the API
receives. `messages` optionally seeds a new conversation with selected user and
assistant text. The bridge only captures context supplied to it; it cannot
automatically read a Codex or ChatGPT conversation.

The command prints a small JSON summary with `status`, `turn_id`, `log_path`,
`text_path`, model, response ID, and request ID. It does not print the key or
generated copy. Read the indicated files. Follow up using the same log:

```sh
python3 skills/no-watermark/scripts/no_watermark.py generate \
  --conversation /absolute/path/to/conversation.json \
  --prompt 'Make the opening warmer and shorten the last paragraph.'
```

A conversation UUID also works with the configured log directory. Follow-ups
retain the previous successful model alias and writing instructions unless
overridden. A failed turn is recorded but excluded from the API history. Initial
`messages` cannot replace an existing conversation. Model changes may be subject
to the API's compatibility requirements for prior reasoning items.

Other options: `--instructions-file`, `--max-output-tokens`, `--output-file`, and
`--dry-run`. A dry run logs a prepared request without spending API tokens.
Successful export replaces `--output-file` when specified; otherwise each
conversation has one current `.md` file beside its JSON log. The JSON retains
earlier successful text.

## Conversation log

Default directory: `~/.local/state/no-watermark/conversations/`. New directories
are private (`700`); JSON and Markdown files are private (`600`). Each log has:

- `messages`: supplied human/context messages and successful API replies.
- `calls`: each turn's exact request payload, response, status, timestamps,
  request ID, usage (in the response), output, and errors.
- `api_history`: successful input and output items for stateless continuation,
  including encrypted reasoning content.
- `latest_output_text` and `latest_text_file`: most recent successful result.
- `provenance`: account-controlled watermarking, explicitly unverified.

Authentication headers and API keys are omitted. The configured key is redacted
if it appears in an error or response; output containing it is not exported.
All calls use the fixed HTTPS OpenAI endpoint with redirects disabled. Requests
set `store: false`; this is not a claim of zero retention. See
[OpenAI's data controls](https://developers.openai.com/api/docs/guides/your-data).

The log is written before the API call and updated atomically. One lock prevents
concurrent writes to the same conversation. There are no automatic retries:
timeouts may mean a request reached the server. An interrupted call stays
`pending`; inspect its outcome before continuing. Recover a stale `.json.lock`
only after confirming no process is using it. Incomplete/refused/failed outputs
are logged and not exported. After a failed revision the previous good text may
still be present: check the **current turn's status**, not only the latest text.

If text export fails after API success, recover `latest_output_text` from the
saved log rather than making the API call again.

## Install the skill

From this checkout:

```sh
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/no-watermark" ~/.codex/skills/no-watermark
```

If that name already exists, inspect it before replacing it. The skill is
self-contained and can also be copied as a folder. Invoke `/no-watermark` or
`$no-watermark` in a Codex chat with local execution. It sends the complete brief
to the script, reads the log, and delivers the exact API-written file. Further
publication edits also go through the API.

The saved file is the canonical copy. If the host model rewrites it, that adds
another generation step outside this bridge. Neither a chat display nor the
skill name proves the text is unwatermarked. ChatGPT needs an execution
environment with Python, file access, and a private config to use this workflow;
ordinary browser chat cannot execute a script on your computer.

## Checks

```sh
python3 -m unittest discover -s tests -v
```

Tests use mocked API responses and cover exact text export, conversation replay,
authentication, private files, failure recovery, redaction, and dry runs. Live
API calls require your key and consume API tokens.

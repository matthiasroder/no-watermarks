# no-watermarks

A publication-writing skill with three explicit execution paths:

- ChatGPT web can use the skills-only `skill.zip` and draft with ChatGPT
  directly, without another API key or external API claim.
- A ChatGPT plugin can call the Responses API through the separately deployed,
  OAuth-protected `web-proxy/` service.
- Codex CLI keeps the original dependency-free Python bridge and private
  `config.toml` workflow.

No path can guarantee that text is watermark-free. See
[CHATGPT_WEB_SETUP.md](CHATGPT_WEB_SETUP.md) for the documented web limitation,
browser installation, authenticated option, costs, and verification steps. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the security boundary.

## Configure

```sh
mkdir -p ~/.config/skills/no-watermark
cp skills/no-watermark/config.example.toml ~/.config/skills/no-watermark/config.toml
chmod 600 ~/.config/skills/no-watermark/config.toml
```

Enter your API key locally in that file and choose the `model`. Optional
`instructions` apply to every call. Keep this config outside the repository.

## Use

```sh
python3 skills/no-watermark/scripts/no_watermark.py < brief.txt
```

The prompt comes from stdin. The command prints a JSON summary with `log_path`
and `status`. By default, logs are saved privately in
`~/.local/state/no-watermark/conversations/`.

Continue a conversation by passing the returned path:

```sh
python3 skills/no-watermark/scripts/no_watermark.py \
  --log /absolute/path/to/conversation.json < revision.txt
```

Use `--config <path>` for another config. Each log contains `messages` (successful
user/assistant turns) and `calls` (timestamp, request payload, raw API response,
and exact output `text`). Read `calls[-1].text` after a successful call. Errors
and incomplete responses are logged when the API returns JSON and cause a
nonzero exit. Failed prompts are excluded from follow-up history. The script
never logs authentication headers or the config, and redacts the configured key.

The interface and config are intentionally small: one model, stdin input, and
JSON output. Requests use `store: false`, and the script makes no automatic
retries. Only run one process at a time for a given log file.

## Local Codex skill

```sh
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/no-watermark" ~/.codex/skills/no-watermark
```

Invoke `/no-watermark` or `$no-watermark`. The skill sends the brief to the API,
reads the JSON, and delivers the exact API text. ChatGPT needs an execution
environment with Python, file access, and the private config to use it.

## ChatGPT package

`skill.zip` is a skills-only ChatGPT plugin package containing exactly one
skill. Build it reproducibly with:

```sh
python3 scripts/package_skill.py
```

That package uses ChatGPT directly and says so. It does not make a separate API
call. After deploying `web-proxy/`, build the API-backed variant with:

```sh
python3 scripts/package_skill.py --mcp-url https://your-host.example/mcp
```

The GitHub Actions **Package ChatGPT skill** workflow performs either build from
a browser, so an installer does not need a local terminal. Never put an API key
in the ZIP or workflow input.

Watermarking depends on your API project/organization settings: disable
**Allow text watermarking** there. This script cannot verify its absence or
disable it per request. See [OpenAI's provenance documentation](https://help.openai.com/en/articles/8912793-provenance-signals-in-openai-generated-content).

## Test

```sh
python3 -m unittest discover -s tests -v
(cd web-proxy && npm ci && npm test)
```

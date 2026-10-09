---
name: no-watermark
description: "Generate or revise publication-ready text through an authenticated Responses API tool, the local Codex bridge, or an explicitly disclosed ChatGPT-native fallback. Use for no-watermark publication drafting; never imply that watermark absence is guaranteed."
---

# No Watermark

Choose one execution path. Never ask the user to paste an API key into a prompt,
store a key in skill files, or claim an external API call occurred when it did
not.

## Authenticated web path

Use this path when the installed No Watermark plugin exposes the
`generate_publication_text` tool.

1. Assemble the complete brief, source material, factual constraints, style
   rules, and requested output. Put it in a user message.
2. Call `generate_publication_text` exactly once. Omit `model` to use the
   server's configured default. Pass `instructions` only when the user supplies
   or requests call-specific writing instructions.
3. For a revision, send the successful prior user/assistant turns plus the new
   revision request in `messages`. Exclude failed or incomplete turns.
4. Require a completed result with nonempty `text`. Return that text verbatim,
   with host commentary outside the publication copy. Do not retry
   automatically; a retry can create another charge.

If the tool is absent or authentication fails, do not substitute ordinary
ChatGPT generation for a request that explicitly requires the Responses API.
Explain that the authenticated plugin connection must be installed or repaired.

## Local Codex path

Use Python 3.11+ and `scripts/no_watermark.py` relative to this skill directory.
The private config is `~/.config/skills/no-watermark/config.toml`; it contains
`api_key`, `model`, and optional `instructions`. Never read the key into model
context, display it, put it in a prompt, or commit it.

Send the complete brief to the script on stdin without interpolating it into
shell code. For revisions, add `--log <same-conversation.json>`. Require exit
code 0 and `status: completed`, then read `calls[-1].text` from the returned log
and deliver it verbatim. Failed turns stay out of follow-up history. Do not retry
automatically. Remove temporary prompt files after use.

## ChatGPT-native path

When the authenticated tool is unavailable and the user did not require an
external API call, ChatGPT may draft directly. State clearly before the copy:
`Using ChatGPT directly; no external Responses API call was made.` Then follow
the same complete-brief and revision discipline. Do not describe this as the
API-backed workflow.

This skill does not publish content. It cannot verify or guarantee that output
is watermark-free. Provenance or watermark behavior depends on OpenAI's current
product policies and supported project or organization settings, not on the
skill name or request payload.

For web setup or failures, read `references/chatgpt-web-setup.md` or
`references/troubleshooting.md` respectively.

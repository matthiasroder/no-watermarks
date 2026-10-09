# ChatGPT web setup

ChatGPT web runs this workflow in one of two honest modes:

- A skills-only plugin can draft with ChatGPT itself. It does not make a separate
  Responses API call and does not use an API project setting.
- A plugin connected to the repository's hosted MCP proxy calls the Responses
  API. The proxy must be deployed first and protected by OAuth.

Standalone skills are currently documented for the ChatGPT desktop app, Codex
CLI, and the IDE extension. ChatGPT web receives skills through plugins. Upload
the default `skill.zip` using the plugin portal's **Skills only** path. For the
API-backed path, build a package with an MCP URL and upload it using **With MCP**.

Never put an API key in this skill, a chat, plugin metadata, or a ZIP. The hosted
proxy reads it from its deployment platform's secret manager.

Full browser-based instructions are in the repository's
`CHATGPT_WEB_SETUP.md`.

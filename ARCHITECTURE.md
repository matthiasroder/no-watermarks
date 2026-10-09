# Architecture

## What the platform supports

The design follows current official OpenAI documentation checked on
2026-10-09:

- A skill is an instruction/resource bundle. Standalone skills are documented
  for the ChatGPT desktop app, Codex CLI, and the IDE extension. Skills reach
  ChatGPT web when bundled in a plugin. A plain `SKILL.md` does not itself
  provide credentials, durable configuration, an API identity, or permission to
  call external services. [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Skills can guide MCP tools, while an MCP server owns live data,
  authentication, authorization, and controlled actions. Declaring a tool
  dependency is not secret storage. [Build plugin skills](https://developers.openai.com/plugins/build/skills)
- ChatGPT can connect to remote MCP servers over streamable HTTP and authenticate
  with OAuth. ChatGPT does not present arbitrary user-provided API keys to an
  MCP server. [MCP authentication](https://developers.openai.com/plugins/build/auth)
- A skills-only plugin ZIP cannot bundle an MCP configuration later. The
  API-backed distribution must be created through the portal's **With MCP**
  path with a real HTTPS endpoint. [Submission errors](https://developers.openai.com/plugins/deploy/submission-errors)

The documentation does not establish a general-purpose persistent secret store,
environment variables, or guaranteed Python execution for a skill running in an
ordinary ChatGPT web conversation. This repository therefore does not rely on
any of those assumptions.

## Decision

The simplest secure web mode is native ChatGPT generation. It requires no extra
key or infrastructure, but it is not a separate Responses API call and cannot
use an API project's settings. The skill discloses that distinction.

For users who specifically require the existing API workflow, the supported
shape is a plugin skill plus a hosted MCP proxy:

```text
ChatGPT conversation
  -> installed no-watermark skill
  -> OAuth access token
  -> hosted MCP proxy
       - validates issuer, audience, signature, expiry, scope, subject
       - enforces model allowlist, input limits, and per-process rate limit
       - reads OPENAI_API_KEY from the host secret manager
  -> OpenAI Responses API (store: false, one request, no automatic retry)
  -> exact publication text
```

The proxy is stateless. ChatGPT passes the successful prior user/assistant turns
again on revisions. This avoids a conversation database and cross-user state.
The local Codex bridge continues to store private JSON logs with permissions
`0600`; the hosted proxy does not store conversation logs. ChatGPT retains its
own conversation according to the user's product settings.

## Security boundary

- The OpenAI key exists only in the hosting secret manager and the outbound
  Authorization header created by the proxy.
- OAuth token validation and a mandatory `ALLOWED_SUBJECTS` allowlist prevent an
  arbitrary authenticated tenant user from charging the project.
- A dedicated OpenAI project, restricted model list, project budget, and
  provider/gateway rate limits limit financial exposure. The in-process limiter
  alone is not sufficient for a multi-instance deployment.
- The proxy does not log or return prompts, model output, bearer tokens, the API
  key, or upstream error bodies. It returns a request ID when available.
- Calls use `store: false` and no automatic retry. An uncertain network outcome
  can still have incurred a charge; the user decides whether to retry.
- OAuth issuance is delegated to an established provider. This repository does
  not implement passwords, sessions, or an authorization server.

## Watermark boundary

The repository controls routing and disclosure, not provenance policy. Neither
the skill nor the proxy verifies watermark status, and neither guarantees
watermark-free output. Current OpenAI policy and supported account/project
settings remain authoritative.

# ChatGPT web setup

## Important platform limitation

As documented on 2026-10-09, standalone skills are available in ChatGPT desktop,
Codex CLI, and the IDE extension. ChatGPT web receives installable skills through
plugins. There is no supported way for a plain skill ZIP to carry a secret API
key or independently authorize Responses API billing.

The repository therefore provides two web choices:

1. `skill.zip` is a skills-only plugin containing exactly one skill. It works
   without an extra key by using ChatGPT's current model and explicitly says
   that no external Responses API call occurred.
2. The API-backed option adds the hosted `web-proxy/` MCP service, OAuth, and a
   plugin package built with that real endpoint. It preserves the separate
   Responses API call, model/instruction configuration, multi-turn revisions,
   `store: false`, and no-retry behavior.

Official references: [Build skills](https://learn.chatgpt.com/docs/build-skills),
[plugin skills](https://developers.openai.com/plugins/build/skills),
[custom MCP servers](https://developers.openai.com/api/docs/guides/custom-mcp-server),
and [MCP authentication](https://developers.openai.com/plugins/build/auth).

## Option A: browser-only, no additional API key

1. Download `skill.zip` from this repository or a release.
2. In ChatGPT web, open **Plugins** and choose **Upload new or existing plugin**.
3. Choose the **Skills only** path and upload `skill.zip`.
4. Resolve any portal scan findings, install the resulting private plugin, and
   open a new conversation.
5. Type `@`, select **No Watermark**, and ask for publication copy.
6. Verify that the response says: `Using ChatGPT directly; no external Responses
   API call was made.` This is the expected honest native path.

Plugin upload, private distribution, and publishing can depend on account and
workspace permissions. If the portal or upload action is absent, the account
does not expose the required web surface; the ZIP cannot enable it.

## Option B: authenticated Responses API path

This option is for the owner of the API billing project. All setup can be done
in browser dashboards, but it requires a hosted service.

### 1. Prepare a dedicated OpenAI project

1. In the OpenAI Platform dashboard, create a dedicated project for this proxy.
2. Select the permitted model, configure a conservative project budget and
   alerts, and create a narrowly scoped service account/API key where the
   account supports those controls.
3. Do not download the key into the repository and do not paste it into ChatGPT.
   It will be entered once in the hosting provider's secret manager.

API usage is billed to this project. ChatGPT subscription charges do not replace
Responses API usage charges for this architecture.

### 2. Configure an OAuth provider

Use an established OAuth 2.1/OpenID provider that supports authorization code
with PKCE, discovery metadata, JWKS, audience validation, and custom scopes.

1. Create an API/resource whose audience is the final MCP URL, for example
   `https://writer.example.com/mcp`.
2. Add the scope `no-watermark.generate`.
3. Create a web client for ChatGPT. The ChatGPT plugin connection screen supplies
   the exact redirect URI; copy that URI into the provider's allowlist.
4. Find the stable subject ID for each permitted user. The proxy requires these
   IDs in `ALLOWED_SUBJECTS`; this prevents every account in the identity tenant
   from spending against the OpenAI project.

The proxy is only a resource server. It deliberately does not issue tokens or
store passwords.

### 3. Deploy the proxy from the browser

1. Choose a container host with GitHub integration, public HTTPS, and a secret
   manager. Import this repository and set the Docker build context to
   `web-proxy`.
2. Add the values documented in `web-proxy/.env.example` through the host's
   dashboard. Mark `OPENAI_API_KEY` as secret. Never use a public build argument.
3. Set `PUBLIC_BASE_URL` to the deployment origin, and set `OAUTH_AUDIENCE` to
   that origin plus `/mcp`.
4. Set `ALLOWED_MODELS` narrowly and `ALLOWED_SUBJECTS` to the comma-separated
   stable user IDs.
5. Deploy. Confirm in a browser that `/` returns `No Watermark MCP proxy` and
   `/.well-known/oauth-protected-resource` returns metadata. Do not place a live
   call just to test billing.

No infrastructure was deployed by this repository change. Hosting and OAuth
provider selection remain the operator's responsibility.

### 4. Build the endpoint-specific ZIP without a terminal

1. Fork the repository on GitHub.
2. Open **Actions** → **Package ChatGPT skill** → **Run workflow**.
3. Enter the deployed URL ending in `/mcp`, such as
   `https://writer.example.com/mcp`. Never enter a secret.
4. Download the `no-watermark-skill` workflow artifact. Inside it is
   `skill.zip`, containing one skill and the remote MCP declaration.

The checked-in `skill.zip` is intentionally the skills-only variant because a
real endpoint was not supplied or deployed.

### 5. Connect and install in ChatGPT

1. Open the ChatGPT plugin portal and upload the endpoint-specific ZIP using the
   **With MCP** path.
2. In **MCPs**, connect the server, verify its domain when prompted, and choose
   OAuth authentication.
3. Enter the OAuth client configuration from the provider. Complete sign-in and
   consent with an allowlisted user.
4. Scan tools and confirm that exactly `generate_publication_text` appears with
   the `no-watermark.generate` scope.
5. Install the private plugin and open a new conversation. Type `@` and select
   **No Watermark**.

### 6. Verify the real execution path

Ask:

> Use No Watermark's authenticated API path to write a two-sentence launch
> announcement. Do not use native ChatGPT generation if the tool is unavailable.

A valid test shows one `generate_publication_text` tool call and returns its
text. Disable the MCP connection and repeat: the skill must report the missing
authenticated path rather than silently drafting. For a revision, ask to change
the tone and confirm the tool receives the prior successful turns plus the new
request.

## External services, accounts, and costs

| Item | Required for native path | Required for API path | Cost notes |
|---|---:|---:|---|
| ChatGPT account with plugin upload/install access | Yes | Yes | Depends on the user's ChatGPT plan/workspace |
| OpenAI API project and key | No | Yes | Responses API usage is billed separately |
| HTTPS container hosting | No | Yes | Provider-dependent; free tiers may sleep or limit traffic |
| OAuth 2.1/OpenID provider | No | Yes | Provider-dependent; an existing organization IdP may suffice |
| Custom domain | No | Not strictly, if the host provides stable HTTPS | Domain registration is optional but production review requires a real reachable endpoint |

## Troubleshooting

- **No web upload option:** the account or workspace lacks plugin authoring
  access. Use ChatGPT desktop/Codex locally, or ask the workspace administrator.
- **Tool is absent:** a skills-only ZIP was installed, or the MCP was not
  connected/scanned. Do not claim an API call occurred.
- **OAuth loop or 401:** check issuer, audience, redirect URI, signing algorithm,
  required scope, and the exact allowlisted subject.
- **HTTP 403-like tool failure:** the token's subject or scope is not authorized.
- **Model rejected:** use the server default or add the model deliberately to
  `ALLOWED_MODELS`.
- **OpenAI HTTP error:** check project model access, budget, and rate limits. The
  proxy returns a request ID when available and does not retry.
- **Incomplete response:** decide manually whether to retry; the first request
  may already have incurred a charge.
- **No saved server conversation:** expected. The web proxy is stateless. The
  ChatGPT conversation supplies successful context again; local Codex retains
  private JSON logs.
- **Watermark concern:** neither mode verifies or guarantees watermark status.
  Review current OpenAI provenance policy and supported account settings.

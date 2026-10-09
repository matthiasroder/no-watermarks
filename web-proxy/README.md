# Authenticated web proxy

This optional service is the secure bridge between a ChatGPT plugin and the
OpenAI Responses API. The skill never receives an API key. The proxy validates
an OAuth access token, restricts callers to an explicit subject allowlist,
allows only configured models, rate-limits each subject, and makes one upstream
request with `store: false`. It never retries or logs request bodies, response
bodies, bearer tokens, or the OpenAI key.

## Deploy

Use a container host that provides HTTPS and a secret manager. Connect the host
to this repository, set the build context to `web-proxy`, and deploy the
`Dockerfile`. Add every variable from `.env.example` in the host dashboard.
Treat `OPENAI_API_KEY` as a secret.

Use a dedicated OpenAI project and service account key where available. Limit
the key to the required Responses capability, restrict `ALLOWED_MODELS`, set a
project budget and alerts, keep `ALLOWED_SUBJECTS` narrow, and add a gateway
rate limit if the host provides one. The in-process limiter is defense in depth,
not a distributed billing control.

The OAuth provider must support authorization code with PKCE and publish OAuth
or OpenID metadata plus JWKS. Configure its API audience to match
`OAUTH_AUDIENCE`, grant `OAUTH_REQUIRED_SCOPE`, and configure ChatGPT with the
provider's client details. The proxy serves protected-resource metadata at
`/.well-known/oauth-protected-resource` and the MCP endpoint at `/mcp`.

The proxy intentionally does not implement an authorization server. Use an
established identity provider rather than creating password, session, or token
issuance code here.

## Run and test locally

Local execution is for developers only; ChatGPT requires a public HTTPS endpoint.

```sh
npm ci
npm test
npm start
```

No live API test runs unless you deliberately deploy and connect the service.

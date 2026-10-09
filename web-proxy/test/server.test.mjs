import assert from "node:assert/strict";
import test from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import {
  MinuteRateLimiter,
  authenticateHeader,
  authorizeClaims,
  createHttpServer,
  generatePublicationText,
  loadConfig,
} from "../server.mjs";


function environment(overrides = {}) {
  return {
    OPENAI_API_KEY: "sk-test-secret",
    DEFAULT_MODEL: "test-model",
    ALLOWED_MODELS: "test-model,second-model",
    DEFAULT_INSTRUCTIONS: "Keep facts.",
    PUBLIC_BASE_URL: "https://writer.example.com",
    OAUTH_ISSUER: "https://issuer.example.com/",
    OAUTH_AUDIENCE: "https://writer.example.com/mcp",
    OAUTH_JWKS_URI: "https://issuer.example.com/jwks.json",
    OAUTH_REQUIRED_SCOPE: "no-watermark.generate",
    ALLOWED_SUBJECTS: "auth0|owner",
    ...overrides,
  };
}


function response(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}


function context(fetchImpl, overrides = {}) {
  const config = loadConfig(environment(overrides));
  return {
    config,
    principal: { subject: "auth0|owner" },
    fetchImpl,
    rateLimiter: new MinuteRateLimiter(config.maxRequestsPerMinute),
  };
}


function within(promise, milliseconds, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}


test("missing configuration fails closed", () => {
  assert.throws(() => loadConfig({}), /PUBLIC_BASE_URL/);
  assert.throws(() => loadConfig(environment({ ALLOWED_SUBJECTS: "" })), /ALLOWED_SUBJECTS/);
  assert.equal(loadConfig(environment()).oauthIssuer, "https://issuer.example.com/");
});


test("claims require the configured subject and scope", () => {
  const config = loadConfig(environment());
  assert.deepEqual(authorizeClaims({ sub: "auth0|owner", scope: "openid no-watermark.generate" }, config),
    { subject: "auth0|owner" });
  assert.throws(() => authorizeClaims({ sub: "auth0|stranger", scope: "no-watermark.generate" }, config));
  assert.throws(() => authorizeClaims({ sub: "auth0|owner", scope: "openid" }, config));
});


test("bearer authentication does not accept other schemes", async () => {
  const config = loadConfig(environment());
  assert.equal(await authenticateHeader(undefined, config), null);
  await assert.rejects(authenticateHeader("Basic abc", config));
  const principal = await authenticateHeader("Bearer token", config, async (token) => ({ subject: token }));
  assert.deepEqual(principal, { subject: "token" });
});


test("successful generation sends exact multi-turn input with store disabled", async () => {
  let captured;
  const fetchImpl = async (url, options) => {
    captured = { url, options };
    return response({
      id: "resp_test",
      status: "completed",
      model: "test-model",
      output: [{ type: "message", content: [{ type: "output_text", text: "Exact copy." }] }],
    });
  };
  const messages = [
    { role: "user", content: "Draft this." },
    { role: "assistant", content: "First draft." },
    { role: "user", content: "Make it warmer." },
  ];
  const result = await generatePublicationText({ messages, instructions: "Warm tone." }, context(fetchImpl));
  assert.equal(result.structuredContent.status, "completed");
  assert.equal(result.structuredContent.text, "Exact copy.");
  assert.equal(captured.url, "https://api.openai.com/v1/responses");
  const payload = JSON.parse(captured.options.body);
  assert.deepEqual(payload.input, messages);
  assert.equal(payload.store, false);
  assert.equal(payload.instructions, "Keep facts.\n\nWarm tone.");
  assert.equal(captured.options.headers.Authorization, "Bearer sk-test-secret");
});


test("upstream errors are sanitized and are not retried", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    return response({ error: { message: "Invalid API key sk-test-secret" } }, 401, { "x-request-id": "req_test" });
  };
  const result = await generatePublicationText({ messages: [{ role: "user", content: "Draft." }] }, context(fetchImpl));
  assert.equal(calls, 1);
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.code, "upstream_error");
  assert.equal(result.structuredContent.request_id, "req_test");
  assert.doesNotMatch(JSON.stringify(result), /sk-test-secret|Invalid API key/);
});


test("incomplete responses fail and do not expose partial text", async () => {
  const fetchImpl = async () => response({
    status: "incomplete",
    output: [{ type: "message", content: [{ type: "output_text", text: "Partial secret draft" }] }],
  });
  const result = await generatePublicationText({ messages: [{ role: "user", content: "Draft." }] }, context(fetchImpl));
  assert.equal(result.structuredContent.code, "incomplete_response");
  assert.doesNotMatch(JSON.stringify(result), /Partial secret draft/);
});


test("disallowed models fail before making a paid request", async () => {
  let calls = 0;
  const result = await generatePublicationText(
    { messages: [{ role: "user", content: "Draft." }], model: "not-allowed" },
    context(async () => { calls += 1; }),
  );
  assert.equal(calls, 0);
  assert.equal(result.structuredContent.code, "model_not_allowed");
});


test("missing principal returns an OAuth challenge without an API call", async () => {
  let calls = 0;
  const ctx = context(async () => { calls += 1; });
  ctx.principal = null;
  const result = await generatePublicationText({ messages: [{ role: "user", content: "Draft." }] }, ctx);
  assert.equal(calls, 0);
  assert.equal(result.structuredContent.code, "authentication_required");
  assert.match(result._meta["mcp/www_authenticate"][0], /oauth-protected-resource/);
});


test("streamable HTTP exposes one OAuth-protected MCP tool", async (t) => {
  const config = loadConfig(environment());
  const server = createHttpServer(config, {
    fetchImpl: async () => { throw new Error("must not call OpenAI without authentication"); },
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  });
  const address = server.address();
  const client = new Client({ name: "test-client", version: "1.0.0" });
  t.after(() => client.close());
  await within(client.connect(new StreamableHTTPClientTransport(
    new URL(`http://127.0.0.1:${address.port}/mcp`),
  )), 5_000, "MCP connect");
  const tools = await client.listTools();
  assert.deepEqual(tools.tools.map((tool) => tool.name), ["generate_publication_text"]);
  assert.deepEqual(tools.tools[0]._meta.securitySchemes, [
    { type: "oauth2", scopes: ["no-watermark.generate"] },
  ]);
  const result = await client.callTool({
    name: "generate_publication_text",
    arguments: { messages: [{ role: "user", content: "Draft." }] },
  });
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent.code, "authentication_required");
  assert.match(result._meta["mcp/www_authenticate"][0], /oauth-protected-resource/);
});

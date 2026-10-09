import { createServer as createNodeServer } from "node:http";
import { pathToFileURL } from "node:url";

import { createRemoteJWKSet, jwtVerify } from "jose";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";


const DEFAULT_SCOPE = "no-watermark.generate";
const jwksCache = new Map();


function splitList(value) {
  return String(value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
}


function required(env, name) {
  const value = env[name]?.trim();
  if (!value) throw new Error(`Missing required configuration: ${name}`);
  return value;
}


function positiveInteger(env, name, fallback) {
  const value = Number(env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer.`);
  }
  return value;
}


export function loadConfig(env = process.env) {
  const publicBaseUrl = new URL(required(env, "PUBLIC_BASE_URL"));
  if (publicBaseUrl.protocol !== "https:" && publicBaseUrl.hostname !== "localhost") {
    throw new Error("PUBLIC_BASE_URL must use HTTPS outside localhost.");
  }
  publicBaseUrl.pathname = "/";
  publicBaseUrl.search = "";
  publicBaseUrl.hash = "";

  const defaultModel = required(env, "DEFAULT_MODEL");
  const allowedModels = new Set(splitList(env.ALLOWED_MODELS || defaultModel));
  if (!allowedModels.has(defaultModel)) {
    throw new Error("DEFAULT_MODEL must be included in ALLOWED_MODELS.");
  }

  const allowedSubjects = new Set(splitList(required(env, "ALLOWED_SUBJECTS")));
  const algorithms = splitList(env.OAUTH_ALGORITHMS || "RS256");
  const requiredScope = env.OAUTH_REQUIRED_SCOPE?.trim() || DEFAULT_SCOPE;
  const resource = new URL("mcp", publicBaseUrl).href;

  return Object.freeze({
    openaiApiKey: required(env, "OPENAI_API_KEY"),
    defaultModel,
    allowedModels,
    defaultInstructions: env.DEFAULT_INSTRUCTIONS?.trim() || "",
    publicBaseUrl: publicBaseUrl.href.replace(/\/$/, ""),
    resource,
    resourceMetadataUrl: new URL(".well-known/oauth-protected-resource", publicBaseUrl).href,
    oauthIssuer: required(env, "OAUTH_ISSUER"),
    oauthAudience: required(env, "OAUTH_AUDIENCE"),
    oauthJwksUri: required(env, "OAUTH_JWKS_URI"),
    requiredScope,
    algorithms,
    allowedSubjects,
    maxRequestsPerMinute: positiveInteger(env, "MAX_REQUESTS_PER_MINUTE", 10),
    maxInputChars: positiveInteger(env, "MAX_INPUT_CHARS", 200_000),
    maxInstructionsChars: positiveInteger(env, "MAX_INSTRUCTIONS_CHARS", 20_000),
    openaiTimeoutMs: positiveInteger(env, "OPENAI_TIMEOUT_MS", 180_000),
    port: positiveInteger(env, "PORT", 8787),
  });
}


function challenge(config, description = "Authenticate to use the writing service") {
  const safeDescription = description.replace(/["\\]/g, "");
  return `Bearer resource_metadata="${config.resourceMetadataUrl}", scope="${config.requiredScope}", error="invalid_token", error_description="${safeDescription}"`;
}


function scopesFromClaims(payload) {
  const scopes = new Set(splitList(payload.scope?.replaceAll(" ", ",")));
  if (Array.isArray(payload.permissions)) {
    for (const permission of payload.permissions) {
      if (typeof permission === "string") scopes.add(permission);
    }
  }
  return scopes;
}


export function authorizeClaims(payload, config) {
  if (typeof payload.sub !== "string" || !config.allowedSubjects.has(payload.sub)) {
    throw new Error("OAuth subject is not authorized.");
  }
  if (!scopesFromClaims(payload).has(config.requiredScope)) {
    throw new Error("OAuth token lacks the required scope.");
  }
  return Object.freeze({ subject: payload.sub });
}


export async function verifyAccessToken(token, config) {
  let jwks = jwksCache.get(config.oauthJwksUri);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(config.oauthJwksUri));
    jwksCache.set(config.oauthJwksUri, jwks);
  }
  const { payload } = await jwtVerify(token, jwks, {
    issuer: config.oauthIssuer,
    audience: config.oauthAudience,
    algorithms: config.algorithms,
  });
  return authorizeClaims(payload, config);
}


export async function authenticateHeader(header, config, verifier = verifyAccessToken) {
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match) throw new Error("Authorization header must use Bearer authentication.");
  return verifier(match[1], config);
}


export class MinuteRateLimiter {
  constructor(limit) {
    this.limit = limit;
    this.buckets = new Map();
  }

  take(subject, now = Date.now()) {
    const minute = Math.floor(now / 60_000);
    const current = this.buckets.get(subject);
    if (!current || current.minute !== minute) {
      this.buckets.set(subject, { minute, count: 1 });
      return true;
    }
    if (current.count >= this.limit) return false;
    current.count += 1;
    return true;
  }
}


function toolError(message, code = "request_failed", extra = {}) {
  return {
    isError: true,
    content: [{ type: "text", text: message }],
    structuredContent: { status: "failed", code, ...extra },
  };
}


function extractOutputText(response) {
  return (response.output ?? [])
    .filter((item) => item?.type === "message")
    .flatMap((item) => item.content ?? [])
    .filter((part) => part?.type === "output_text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}


export async function generatePublicationText(args, context) {
  const { config, principal, fetchImpl, rateLimiter } = context;
  if (!principal) {
    return {
      ...toolError("Authentication is required.", "authentication_required"),
      _meta: { "mcp/www_authenticate": [challenge(config)] },
    };
  }
  if (!rateLimiter.take(principal.subject)) {
    return toolError("Rate limit reached. Wait before making another paid request.", "rate_limited");
  }

  const model = args.model || config.defaultModel;
  if (!config.allowedModels.has(model)) {
    return toolError("The requested model is not allowed by this deployment.", "model_not_allowed");
  }
  const inputChars = args.messages.reduce((total, message) => total + message.content.length, 0);
  if (inputChars > config.maxInputChars) {
    return toolError("The conversation is larger than this deployment allows.", "input_too_large");
  }
  const callInstructions = args.instructions?.trim() || "";
  if (callInstructions.length > config.maxInstructionsChars) {
    return toolError("The writing instructions are larger than this deployment allows.", "instructions_too_large");
  }
  const instructions = [config.defaultInstructions, callInstructions].filter(Boolean).join("\n\n");
  const payload = { model, input: args.messages, store: false };
  if (instructions) payload.instructions = instructions;

  let reply;
  try {
    reply = await fetchImpl("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.openaiApiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(config.openaiTimeoutMs),
    });
  } catch {
    return toolError("The OpenAI API request could not be completed. It was not retried.", "upstream_unavailable");
  }

  const requestId = reply.headers.get("x-request-id") || undefined;
  if (!reply.ok) {
    return toolError(`The OpenAI API returned HTTP ${reply.status}. It was not retried.`, "upstream_error",
      requestId ? { request_id: requestId } : {});
  }

  let response;
  try {
    response = await reply.json();
  } catch {
    return toolError("The OpenAI API returned an unreadable response.", "invalid_upstream_response",
      requestId ? { request_id: requestId } : {});
  }
  const text = extractOutputText(response);
  if (response.status !== "completed" || !text.trim()) {
    return toolError("The OpenAI response was incomplete or contained no publication text.", "incomplete_response",
      requestId ? { request_id: requestId } : {});
  }

  return {
    content: [{ type: "text", text }],
    structuredContent: { status: "completed", model: response.model || model, text },
    _meta: response.id ? { response_id: response.id } : {},
  };
}


export function createMcpServer(context) {
  const securitySchemes = [{ type: "oauth2", scopes: [context.config.requiredScope] }];
  const server = new McpServer(
    { name: "no-watermark-api", version: "0.1.0" },
    { instructions: "Use generate_publication_text for one paid Responses API call. Never retry automatically." },
  );
  server.registerTool(
    "generate_publication_text",
    {
      title: "Generate publication text",
      description: "Use this for one authenticated OpenAI Responses API call that drafts or revises publication-ready text. Include successful prior turns for revisions. Each call can incur API charges; never retry automatically.",
      inputSchema: {
        messages: z.array(z.object({
          role: z.enum(["user", "assistant"]),
          content: z.string().min(1),
        })).min(1).max(64),
        model: z.string().min(1).max(100).optional(),
        instructions: z.string().optional(),
      },
      outputSchema: {
        status: z.enum(["completed", "failed"]),
        model: z.string().optional(),
        text: z.string().optional(),
        code: z.string().optional(),
        request_id: z.string().optional(),
      },
      securitySchemes,
      _meta: { securitySchemes },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        openWorldHint: true,
      },
    },
    async (args) => generatePublicationText(args, context),
  );
  return server;
}


function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "authorization, content-type, mcp-protocol-version, mcp-session-id");
  res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id, WWW-Authenticate");
}


function sendJson(res, status, body, headers = {}) {
  res.writeHead(status, { "content-type": "application/json", ...headers });
  res.end(JSON.stringify(body));
}


export function createHttpServer(config, dependencies = {}) {
  const fetchImpl = dependencies.fetchImpl || fetch;
  const verifier = dependencies.verifyToken || verifyAccessToken;
  const rateLimiter = dependencies.rateLimiter || new MinuteRateLimiter(config.maxRequestsPerMinute);

  return createNodeServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
    const metadataPaths = new Set([
      "/.well-known/oauth-protected-resource",
      "/.well-known/oauth-protected-resource/mcp",
    ]);

    if (req.method === "GET" && metadataPaths.has(url.pathname)) {
      sendJson(res, 200, {
        resource: config.resource,
        authorization_servers: [config.oauthIssuer],
        scopes_supported: [config.requiredScope],
      });
      return;
    }
    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "text/plain" });
      res.end("No Watermark MCP proxy\n");
      return;
    }
    if (url.pathname !== "/mcp") {
      res.writeHead(404).end("Not Found");
      return;
    }
    setCors(res);
    if (req.method === "OPTIONS") {
      res.writeHead(204).end();
      return;
    }
    if (!new Set(["POST", "GET", "DELETE"]).has(req.method)) {
      res.writeHead(405).end("Method Not Allowed");
      return;
    }

    let principal = null;
    try {
      principal = await authenticateHeader(req.headers.authorization, config, verifier);
    } catch {
      sendJson(res, 401, { error: "invalid_token" }, { "WWW-Authenticate": challenge(config, "The access token is invalid or unauthorized") });
      return;
    }

    const server = createMcpServer({ config, principal, fetchImpl, rateLimiter });
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    res.on("close", () => {
      transport.close();
      server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res);
    } catch {
      if (!res.headersSent) res.writeHead(500).end("Internal server error");
    }
  });
}


function isEntrypoint() {
  return process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
}


if (isEntrypoint()) {
  try {
    const config = loadConfig();
    createHttpServer(config).listen(config.port, () => {
      console.log(`No Watermark MCP proxy listening on port ${config.port}`);
    });
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Invalid configuration.");
    process.exit(1);
  }
}

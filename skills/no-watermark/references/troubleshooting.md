# Troubleshooting

## The API tool is missing

The installed package is probably the skills-only variant, or the MCP connection
was not enabled. Do not claim to have used the Responses API. Install or repair
the authenticated No Watermark MCP plugin.

## Authentication is requested repeatedly

Reconnect the plugin account. The OAuth provider must issue a token whose
issuer, audience, subject, algorithm, and scope match the proxy configuration.
The subject must be in `ALLOWED_SUBJECTS`.

## The tool returns an authentication error

Do not retry. Reconnect once after the deployment owner confirms the OAuth
configuration. Repeated calls will not repair a bad token.

## The tool reports an OpenAI API error

Do not retry automatically. The deployment owner should check the dedicated
OpenAI project's model access, budget, rate limits, and server configuration.
The proxy deliberately does not return upstream response bodies or credentials.

## A model is rejected

Use the server default or a model listed in the deployment's `ALLOWED_MODELS`.

## A revision forgot the earlier draft

Send successful prior user and assistant turns in `messages`, followed by the
new revision request. Do not include unsuccessful calls.

## The output may contain a watermark

The skill cannot inspect or guarantee watermark status. Review current OpenAI
provenance documentation and the applicable project or organization settings.

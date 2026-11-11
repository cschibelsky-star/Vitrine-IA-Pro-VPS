# Vitrine Avello Gateway V2 — isolated prototype

Independent MCP Streamable HTTP adapter for the Avello Gateway API.

**Status:** source-only prototype. No deployment, authentication test, MCP client discovery, or plugin installation has been completed.

- Fixed upstream: `https://avellogateway.online/v1/models`
- Tools: `gateway_status`, `gateway_models`
- Environment variable: `AVELLO_V2_API_KEY` (inject securely at runtime; never commit)
- No inference, no write actions, no remote execution
- Authentication at the public MCP ingress **must** be configured and verified before exposing it. Do not expose this prototype as-is.
- Python dependency: `mcp` (version to be pinned and reviewed before deployment)
- Run offline tests: `python -m unittest discover -s integrations/avello-gateway-v2/tests -v`

Acceptance gate: offline tests passing, approved ingress auth, fixed-host outbound allowlist, successful authenticated catalog GET, MCP tools discovery, explicit HML approval. Production requires separate authorization.

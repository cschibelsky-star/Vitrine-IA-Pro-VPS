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

## GitHub App authentication (isolated draft, PR #75)

An optional server-side provider lives in `github_app_auth.py`. It signs
short-lived RS256 JWTs and requests installation tokens restricted to
`JARVIS` with `actions:write` and `contents:read`. It requires the
`cryptography` Python package at runtime. This provider is **not connected**
to the existing dispatch adapter or MCP registry and performs no network
requests unless explicitly called by trusted server-side code.

Required server-only configuration (do not commit values):
`VIA_GITHUB_APP_ID`, `VIA_GITHUB_APP_INSTALLATION_ID`, and
`VIA_GITHUB_APP_PRIVATE_KEY_PEM`. The operator-reported GitHub App
ID is 4739135; do **not** assume that the separately observed installation
143831588 belongs to this App until a signed GitHub API request proves it.
Never put the private key or installation token in MCP requests, logs,
PR comments, or client-side settings.

CI evidence: run 43617771216 completed successfully on commit
`aa735654e94e75afabe46ac3eff874e354a32d08`: 30 offline tests
passed and only two read-only MCP tools were registered. Offline tests
use generated RSA keys and a fake HTTP opener; they do not verify live
GitHub App permissions, real dispatch, or deployment.

Activation gates remain closed: prove App/installation association,
verify authorized trusted approval issuer and ingress propagation,
confirm workflow dispatch availability on GitHub's default branch,
review runtime dependencies and secret injection, perform isolated
authenticated end-to-end verification with explicit approval, then
separately authorize any HML deployment. No merge or production changes.

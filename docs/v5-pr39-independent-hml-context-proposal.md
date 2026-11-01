# PR #39 — independent HML context proposal (not deployed)

This file is a **review proposal**, not an active manifest. Do not copy it into the production manifest registry or grant a policy entry without independent approval.

## Live read-only preflight (2026-11-01)

- Candidate project ID `v5-pr39-isolated-hml`: `manifest_not_found`. The name is available **in the queried registry at the time of inspection**, not a reservation.
- Existing validation contexts `v5-0-5-13-recovery-validation` and `v5-global-inventory-validation` are allowlisted but have modified checkouts and stopped historical candidate containers. Do not reuse or restart them.
- PR #39 CI #41320005189 passed; it does not authorize deployment.

## Proposed isolated manifest (illustrative; no secrets)

```json
{
  "id": "v5-pr39-isolated-hml",
  "name": "V5 PR39 Isolated HML",
  "workspace_root": "/srv/projects/v5-pr39-isolated-hml",
  "repository": {
    "url": "https://github.com/cschibelsky-star/Vitrine-IA-Pro-VPS.git",
    "branch": "fix/v5-candidate-no-docker-socket-20261101",
    "directory": "repository"
  },
  "shared_directories": [],
  "docker": {
    "compose_file": "docker-compose.v5-recovery-candidate.yml",
    "project_name": "v5-pr39-isolated-hml"
  },
  "runtime": {
    "env_file": ".env.runtime",
    "allowed_keys": []
  },
  "domains": {"homologation": [], "production": []},
  "release": {"directory": "releases", "exclude": [".git", ".env", "shared", "data", "uploads", "logs", "vendor", "node_modules"]}
}
```

**Important:** this is a proposed shape, not evidence the current connector accepts empty runtime keys. The live `_runtime_config` and controlled Compose helper must be tested before adoption; never create fake Roteia secrets to satisfy an unrelated check.

## Required independent approvals and gates

1. Operator confirms clean, isolated workspace creation and exact approved Git SHA, not merely a moving branch.
2. Policy owner reviews a candidate-specific entry for **this** project ID and **this** Compose file. Begin with read-only status/logs. Explicitly approve any build/up permission only after the bootstrap executor and rollback have been verified. No wildcard or extension of `vitrine-ia-pro-vps` permissions.
3. Confirm host port `127.0.0.1:18867` is free, audit log mount is isolated, and no shared host Docker socket exists. Compose project identity is unique; PR #39 removed fixed `container_name`.
4. Check that a candidate with `read_only: true` can write only to intended tmpfs/log paths. Verify `internal: true` network, cap_drop, no-new-privileges and expected MCP connectivity.
5. Resolve `runtime_env_not_configured` by reviewed candidate-only configuration or read-only config-path improvement, not by importing production secrets.
6. Record baseline health of V5 and TV Sumaré, maintenance authorization, exact rollback procedure and operator sign-off before any VPS container start.

## Explicit non-actions

No production checkout change, manifest creation, secret import, policy mutation, Docker start, merge, or deployment is authorized by this proposal.

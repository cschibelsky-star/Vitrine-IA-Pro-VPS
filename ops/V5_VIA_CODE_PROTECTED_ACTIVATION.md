# Controlled V5 VIA-CODE-01 bootstrap and rollback

This file is a **runbook, not an authorization to deploy**. The project currently running
`vitrine_mcp_v5` must not be updated by an unverified Compose `up`.

## Verified baselines (2026-11-02 / 2026-11-03 UTC)

- Live: `vitrine_mcp_v5`, image `vitrine-v5-factory-via-hml:fix2`,
  immutable image ID `sha256:c7789a50fa253f2450848ee6407dfffed8dd576048672c96c2023683a1be372b`;
  main endpoint `127.0.0.1:8867`, healthy.
- Working tree `/srv/projects/vitrine-vps-mcp-v59-integration/repository`,
  checked-out branch `feat/roteia-vps-isolated-integration-20261022`.
- Compose source `docker-compose.connector-v5.yml` contains **an older image tag**
  (`vitrine-publication-guard-v5:20261010`) than the image actually running.
  Consequently, using the original Compose alone for `up` is **not safe**.
- Candidate: `vitrine-v5-via-code-candidate:20261102`, isolated
  `vitrine_v5_via_code_candidate`, `127.0.0.1:18869`, MCP tool verified by
  local FastMCP `list_tools()` health check. Candidate is **not a paid test**.
- PR #36 is not independently validated in this additive candidate; the
  addition covers PR #47 tool registration only.

## Required protected administrative cutover

1. Record live image ID, Compose service configuration, live FastMCP tool list,
   and current health from the **approved operator channel**. Do not copy or
   print the runtime env file, credentials or auth headers.
2. Capture the live service image to a uniquely named rollback tag using the
   immutable image ID, and preserve the checked-out Git branch. Confirm the
   rollback tag resolves to exactly the same image ID.
3. Confirm the candidate image is present and has successfully completed MCP
   live-tool-list health check. Validate the intended Compose overlay using
   `docker compose config` with secret redaction; do not paste output
   containing environment values into chat.
4. The authorized **narrow installer** must select precisely service
   `connector_v5`, preserve all existing mounts, ports, healthcheck,
   routing labels and environment references, set only the image to the tested
   candidate, and recreate only this service with `--no-build --no-deps`.
   It must not start migrations, extra services or change the repository.
5. After the switch, verify MCP endpoint and old baseline tools alongside the
   new `project_roteia_via_code_pilot_execute` schema. Verify absence of
   missing tools using a pre-cutover catalog snapshot and reject any regression.
   Then verify the protected Cockpit/Core integrations.
6. If health, tool registry, authentication or regression checks fail, restore
   the exact captured image ID through the same narrow installer, verify the
   original endpoint and publish a rollback report.
7. Only after activation may `VIA-CODE-01` be called, **once**. This is a
   separate paid experiment and does not imply the Claude answer is accepted.

## Blocker and acceptance criteria

Current connector tools support a bounded Compose build/up/status, but they do
not expose a dedicated atomic **image-only update with snapshot and rollback**
and they cannot run a safe specific script directly. Prior V5 attempts produced
`controlled_service_not_allowed`. A general-purpose SSH/shell executor is
not an acceptable replacement.

The one-time administrative bootstrap, if needed, must install this dedicated
image-only update capability rather than remove existing service allowlists.
The `EXECUTAR` confirmation is required for **every** operation that changes
the live V5. If the required snapshot, rollback, or tool catalog cannot be
verified, abort *before* recreating the service.

Do not claim full V5 self-update is ready until a separate real rollback
rehearsal and tool-catalog comparison have succeeded.

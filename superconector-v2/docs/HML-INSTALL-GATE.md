# Superconector V2 — HML persistent installation gate

Status: BLOCKED — V5 runtime allowlist has not been updated. This is an operational approval checklist, not evidence of an installation.

## Verified inputs
- Superconector source: `feature/superconector-v2-hml`, path `superconector-v2/server/`.
- V2 Compose: `superconector-v2/server/docker-compose.hml.yml`, project `vitrine-super-v2-public-hml`, service `public_mcp`.
- HML VPS manifest ID: `vitrine-superconector-v2-hml`; repository checkout in `/srv/projects/vitrine-superconector-v2-hml`.
- Runner CI `42933476006`: real Compose build, start, MCP initialize/list/call with 3 informational tools passed. Not a persistent VPS install.
- Updated safety checks CI `42933804333`: passed.
- V5 PR `#71` is draft, mergeable, unmerged; isolated V5 candidate CI `42932472054` passed 33-tool MCP discovery.
- Active V5 reports version `0.5.14-runtime-secret-import`, but `project_compose_service_status(public_mcp)` returns `controlled_service_not_allowed`.
- `project_docker_status(vitrine-superconector-v2-hml)` lists no container.

## Approval gates (not granted)
1. Authorize separately the exact V5 runtime update or another reviewed, equivalently restricted HML executor. PR merge is a separate explicitly approved operation. Do not silently replace an active V5 container.
2. Verify resulting V5 startup and no regression against the live service and TV Sumaré protection.
3. Revalidate V5 policy includes only project `vitrine-superconector-v2-hml`, Compose path `superconector-v2/server/docker-compose.hml.yml`, and service `public_mcp` for controlled `build` and `up`. No `run_once` permission.
4. Validate workspace Git state, commit and Compose configuration on host before mutation; do not reset any dirty tree.
5. Build ONLY `public_mcp` through approved controlled operation and verify success.
6. Start ONLY `public_mcp`, using approved scoped HML operation. Confirm container status/health and the host-local endpoint `127.0.0.1:8878/mcp`.
7. Test MCP `initialize`, `tools/list`, `tools/call` on all 3 informational tools from host or approved probe. Validate unchanged V5 and TV Sumaré.
8. If failed, stop and inspect non-sensitive logs; do not restart or change unrelated services. Any rollback of runtime or destructive operation requires separately approved change plan.

## No premature external exposure
- The V2 informational MCP service has no OAuth enforcement. It must not be exposed to public internet before per-user authentication, tenant authorization, audit, origin protections, and HTTPS are implemented and tested.
- The bridge network allows egress; reassess egress isolation before operational upstream access.
- Public app registration/review and connection from ChatGPT are separate later gates.
- No merge, production deploy, workspace replacement, migration, credential extraction, or public release is authorized by this document.

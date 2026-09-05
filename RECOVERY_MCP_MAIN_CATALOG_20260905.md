# Recovery MCP Main Catalog — 2026-09-05

## Scope
Reconcile the main MCP runtime catalog after VPS rebuild without changing V5, application projects, databases, migrations, Social, Factory, Marketing, or Cursos IA.

## Runtime currently restored
- Public endpoint: `https://mcp.vitrineiapro.com.br/mcp`
- Local service: `127.0.0.1:8765`
- Broker: `vitrine_mcp_ops_broker` on 8770
- MCP container: `vitrine_vps_mcp_connector`
- Docker project: `vitrine-vps-mcp-main`
- HostGator SSH: `cris1649@50.6.138.104:2222`
- HostGator home: `/home1/cris1649`
- HostGator key path: `/root/.ssh/hostgator_ops`

## Confirmed healthy capabilities
- MCP HTTP transport responds on `/mcp`
- `system_health`
- `hostgator_health`
- VPS -> HostGator SSH
- Let's Encrypt certificate for `mcp.vitrineiapro.com.br`

## Confirmed catalog/runtime divergence
The Chat connector advertises tools that are not registered by the restored runtime. Confirmed examples:
- `connector_health` -> Unknown tool
- `connector_tree` -> Unknown tool
- `preserve_git_worktree` -> Unknown tool

This proves that transport is healthy while the runtime registry is incomplete.

## Source layers identified
1. Historical base MCP: `cschibelsky-star/vitrine-ai-pro`, branch `feature/vps-mcp-connector-readonly`.
2. Stabilization/runtime layer: `cschibelsky-star/Vitrine-IA-Pro-VPS`, branch `fix/connector-stabilization-v2`.
3. V4 HostGator layer: `feature/v4-hostgator-remote-ops`.
4. AI Dev Hub / project-manager evolution: `feature/ai-dev-hub-connector`.

## Important compatibility blocker
`connector-v2/install_connector_v2.py` from `fix/connector-stabilization-v2` supports `CONNECTOR_ROOT`, but it expects the target `ops_broker.py` to already contain:

```python
from via_operations import router as via_operations_router
```

The currently restored historical base does not contain this prerequisite. Applying the installer directly would reproduce the previous failure and must not be forced.

## Existing release gate
`feature/v4-hostgator-remote-ops/bootstrap/install_connector_release.py` already provides:
- full backup before install;
- source tests;
- py_compile gates;
- compose validation;
- Docker rebuild/up;
- health wait;
- Streamable HTTP registry probe;
- rollback on failure.

Its registry gate requires at least:
- `project_deploy`
- `connector_health`
- `project_context`
- `project_write_file`
- `project_php_lint`

## Recovery rule
Do not replace the current healthy runtime until a consolidated candidate passes offline/source gates and preserves the current HostGator integration and Traefik routing.

## Next reconciliation gate
Locate the canonical VIA operations layer that supplies `via_operations.py` and its router registration, then compose:

`historical base -> VIA operations prerequisite -> connector stabilization v2 -> project manager -> HostGator remote ops`

Only after this chain validates should the runtime at `/srv/connectors/vitrine-vps-mcp-main` be replaced/rebuilt.

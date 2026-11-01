# V5 recovery candidate — authorized bootstrap and rollback (PR #39)

Status: **runbook only**. No VPS deployment is authorized by this document. GitHub is source of truth; test HML before production.

## Verified evidence and blockers

- GitHub Actions #41316626158: static isolation, image build, isolated MCP boot, health, missing-manifest read and denied mutation passed. CI used `docker run --network none`; it did **not** exercise this Compose on the VPS.
- V5 manifest `vitrine-ia-pro-vps` targets `recovery/v5-0.5.14-runtime-secret-import`, workspace `/srv/projects/vitrine-vps-mcp-v59-integration`, repository directory `repository`. The currently observed checkout was on `feat/roteia-vps-isolated-integration-20261022`; do not change or clean that checkout.
- Manifest `docker.compose_file` is empty; `project_compose_explicit` returned `runtime_env_not_configured`.
- `project_compose_service_status` for `connector_v5_recovery_candidate` returned `controlled_service_not_allowed`. Do not bypass policy or silently add service permissions.
- `ROTEIA_API_KEY`, `ROTEIA_API_BASE_URL`, `ROTEIA_TEST_MODELS` are reported `configured:false`. The candidate Compose does not reference these variables; do **not** import or invent Roteia credentials merely to unblock Compose. Diagnose whether the executor requires an env file even when not used.

## Preconditions — all mandatory

1. Obtain explicit authorization for a **separate privileged bootstrap executor** and a maintenance window; identify the operator and approved target host. Never use the V5 self-update endpoint to update itself.
2. Verify PR #39 head, approved CI, branch provenance, rollback owner, free disk space, image tag/digest, and existing V5/TV Sumaré health. Record evidence outside the container.
3. Create an **independent clean checkout** of the approved Git SHA, outside the active dirty checkout, with no `git reset --hard`, `git clean`, force checkout, or mutation of production branches.
4. Confirm existing network and bind paths; check the audit log mount is writable only where intended, while manifests and workspaces are read-only. No Docker socket bind, no production network attachment.
5. Review candidate threat model: dedicated `internal: true` network, read-only root filesystem, `cap_drop: [ALL]`, `no-new-privileges`, localhost port 18867. Internal network blocks external egress; test FastMCP with loopback on host, not a remote client. No production credentials in CI or logs.
6. Resolve the policy/allowlist denial **through a reviewed, authorized change to the official executor**, not by renaming the service or bypassing checks. Confirm this is approved separately from PR #39.
7. Decide whether a candidate-specific project manifest and runtime env file are needed. Do not repoint the existing `vitrine-ia-pro-vps` manifest or import Roteia secrets without documented necessity. If an empty runtime env is permitted, use only a separate candidate context with least privilege and no secrets.

## Controlled HML verification (only after prerequisites)

1. Back up relevant candidate manifest/configuration and record hashes; snapshot current health, network, container list, and port occupancy. Never copy raw secrets into audit records.
2. Validate Compose syntax and effective mounts/network in the independent checkout, then build and start **only** `connector_v5_recovery_candidate` with the approved privileged executor. Do not run broad `docker compose up` or touch `connector_v5` production.
3. Confirm localhost bind, dedicated internal network, no Docker socket, no additional host mounts, no privileges, and no unexpected restart policy.
4. Run MCP `connector_health`, `project_manifest` on a nonexistent fixture, and an unconfirmed `project_manifest_create` to verify rejection. Never send `confirm=EXECUTAR` for mutation tests on a real host.
5. Verify denial of operational Docker mutations is **expected** for this socketless candidate. This is a **read-only recovery candidate**, not proof that V5 controlled Docker operations work.
6. Monitor logs, health, CPU/memory, and effects on existing V5 and TV Sumaré. Capture evidence and obtain HML approval before any production proposal.

## Rollback and stop conditions

- Stop immediately on changed production health, unexpected port/network exposure, policy denial, filesystem write, missing backup, secret leakage, or ambiguous Compose target.
- Using the approved executor, stop and remove **only** the candidate service/container/network created by this run; leave production services and the existing checkout intact. Restore candidate-specific manifest/config from verified backups, if changed.
- Recheck production V5 and TV Sumaré health, ports, networks, logs and repository status. Document rollback evidence and unresolved failures.
- Do not merge PR #39, deploy, import secrets, modify policy, or start the candidate merely because CI passed.

## Acceptance

A signed HML report must show the exact Git SHA, executor authorization, isolated checkout, policy change approval if required, Compose configuration, health/MCP test outputs, negative mutation tests, monitoring, and successful rollback drill. Otherwise keep PR #39 draft and production unchanged.

## Source-level diagnosis after CI #41318749839 (2026-11-01)

- `connector-v5/main.py::project_compose_explicit` resolves the manifest runtime configuration **before** dispatching even the read-only `config` action. If the configured runtime file does not exist, it returns `runtime_env_not_configured`. This explains the observed error independently of whether the candidate Compose actually needs Roteia keys. Do not import secrets as a workaround.
- `connector-v5/controlled_operations_patch.py::project_compose_service_status` checks the service against `CONTROLLED_COMPOSE_POLICY[project_id]["services"]` **before** resolving Compose or runtime configuration. The candidate service is not currently permitted, so `controlled_service_not_allowed` is expected. Adding it to the live allowlist without approved policy review is not authorized.
- The controlled Compose helper additionally restricts `compose_files` and expects an existing runtime env file. Thus an allowlist change alone would not make HML operational.
- Recommended separation: keep the current V5 connector policy unchanged; introduce a separately approved bootstrap pathway for the isolated candidate. Evaluate a candidate-only manifest with an intentionally non-secret runtime env file, or an explicit read-only `config` implementation that does not demand an unrelated runtime file. Any change requires unit tests, CI and review before VPS execution.
- CI #41318749839 passed actual Compose startup with local fixtures, but does not validate host policy, VPS mounts or executor authorization.

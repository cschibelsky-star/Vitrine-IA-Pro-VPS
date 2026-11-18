# Mission grant issuer — development-only contract

This branch adds an offline RS256 signer library and isolated tests. It **does not**
add an API endpoint, credential, deployment, or enable mission execution.

## Trust boundary

The institutional identity layer (not the executor) MUST authenticate the human
or agent, authorize the specific mission in a trusted persistent store, and
supply a canonical immutable `ApprovedMission` to the signer. The callback
`lookup_approval(mission_id, approval_id)` must read from that trusted store.
The caller MUST prohibit revocation, expired approvals, reuse of one-shot
approvals, or mismatched operation/tenant. The callback is not an approval
service and an in-memory value supplied by a caller is not a real approval.

Each grant includes a signed random `jti`. The proposed executor now checks a pre-provisioned SQLite ledger in a single `BEGIN IMMEDIATE` transaction: it validates mission approval, revocation, expiry, tenant, subject, profile and source SHA, then consumes the unique `jti` before running any profile. Unknown, unavailable or unwritable ledgers fail closed. This is **code only** and has not been deployed.\n\nThe ledger is not automatically created by the executor. A separately authenticated institutional approval service must provision immutable approvals, revoke them, and provide a dedicated durable private mount writable by the unprivileged executor. No public administration endpoints. The current HML Docker Compose has a read-only filesystem without that mount, and the executor remains disabled. SQLite is scoped to one persistent executor replica, not a distributed multi-instance deployment.\n\nTokens must be transmitted only over authenticated private channels. Private
keys must be server-side only and must never appear in the Git repository,
public MCP, executor container, logs, or conversation. Issuer and audience
must be configured explicitly; the illustrative `.invalid` domain in tests is
NOT a provider.

## Mandatory gates before enabling HML

1. Identify institutional authenticated identity source and authoritative
   audit/approval store with revocation and single-use enforcement.
2. Bind the trusted stored approval to the user, tenant, profile and pinned
   source SHA. Review subject authorization and operation audit semantics.
3. Provision separate HML signing key securely, pin public key on executor,
   and verify rotation/revocation handling without disclosing private key.
4. Validate and independently review the transactional one-time grant ledger,
   provision durable storage/approval records through an authorized institutional
   service, confirm revocation semantics and test restart/concurrent replay.
   The code on this branch alone does not satisfy this operational gate.
5. Ensure SHA is cryptographically tied to an immutable checkout. Existing
   executor checks only SHA format/equality, not repository provenance.
6. Run negative and positive request tests through private HML network,
   including expired, invalid signature, replay, cross-tenant, wrong profile,
   approval revocation and mismatched SHA.
7. Independent review and explicit enablement approval. Do not expose port
   8091 or set `SUPER_EXECUTOR_HML_ENABLED=true` beforehand.

## Local tests

`python -m unittest discover -s superconector-v2/experiments/executor/tests -p 'test_mission_grant_*.py' -v`

Requires `PyJWT[crypto]`. The test generates an ephemeral RSA key in memory.
No production keys, Docker socket, or external HTTP connections are used.


## 2026-11-17 review — trust boundary and isolated ledger candidate

This review is a preliminary engineering assessment, NOT independent sign-off.

- Packaging: `Dockerfile.private` includes the verification/consumption library.
- Optional overlay: `docker-compose.private-ledger-hml.overlay.yml` specifies a
  host-provisioned persistent private bind mount, no automatic creation, and
  retains `SUPER_EXECUTOR_HML_ENABLED=false`. This overlay is NOT applied.
- Provisioning ownership: only an authenticated institutionally operated
  authorization service may register/revoke approvals. The executor must
  never expose admin/provisioning operations to clients.
- **Critical blocker:** SQLite uses database-file write permissions rather
  than per-table grants. Sharing a writable SQLite database with the executor
  means the executor's account can potentially rewrite `approved_missions`.
  Application-level conventions are NOT a security boundary. Do not claim
  exclusive institutional provisioning when this shared-write design is used.
- Required production-grade alternative: move the authoritative approval
  records to a separately owned service/store. Have a tightly scoped internal
  authorization service transactionally validate revocation and consume grants
  through a private authenticated channel; the executor receives no write access
  to the authoritative approvals store. Evaluate atomicity, durability, replay,
  service-down fail-closed behavior, audit and key management in an independent review.
- Other gates: source-SHA provenance, locked-down private execution path,
  operator identity, revocation under concurrent requests, backup/restore and
  fail-closed startup. No HML activation before all gates pass.

The optional shared-SQLite mount can be used **only for disposable isolated
engineering tests** with fictitious approvals. It is not a trustworthy
institutional approval register for real missions.


## Private approval authority candidate (2026-11-17)

**Not deployed or activated.** The approval authority runs as UID 10002,
is independent from the executor UID 10001 and exposes no TCP port.
It owns the persistent SQLite store under a mount that is NOT present
in the executor container. Its only HTTP route is POST /internal/consume
over a preprovisioned Unix-domain socket. The executor mounts the socket
directory read-only and forwards the original signed grant; it never
receives write access to the database.

`docker-compose.private-ledger-hml.overlay.yml` is a candidate only;
do not apply until review, preprovisioned directory ACLs, trusted
institutional issuance, immutable pinned checkout, and real HML tests.
The authority and executor must use the same pinned public verification
key and SHA. An issuer private key must never be mounted into either.

**Trust gaps, not waived by passing CI:**
- Unix socket filesystem ACLs and host bind ownership must be validated
  on the target VPS, including denial of access from unrelated containers.
- The service authenticates bearer mission grants, not an independent
  caller identity. The socket must be exclusively reachable by the
  intended executor, and grants must be kept private. The host's Docker
  administration remains a trusted boundary.
- A separately authenticated institutional provisioning process must
  still create/revoke immutable approvals. No provisioning API is exposed.
- A single SQLite store and instance must be retained for this candidate.
  Protect durability, startup verification, backups, permissions and
  approval audit trail. Test service termination/network isolation.
- Current consume-then-execute ordering prevents replay but can consume
  an authorization even when a subsequent subprocess fails. This is
  fail-closed, but requires explicit operational retry policy.
- No independent security review has signed off this design; no live
  mission authority, key issuance, approval provisioning, or HML deploy.

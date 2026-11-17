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

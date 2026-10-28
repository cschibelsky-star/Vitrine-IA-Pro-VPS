# Official branch configuration

`project_manifest_branch_configure` updates only `repository.branch` of an existing project manifest. It requires `confirm="EXECUTAR"`, the expected current branch, the destination branch, and its expected 40-character remote commit. It checks the registered GitHub repository with `git ls-remote`, without fetching or changing the checkout.

The operation preserves unknown manifest fields, creates an exclusive backup with mode 0600, records prepared/completed audit events, and replaces the JSON atomically. A per-project advisory lock serializes calls to this operation. The final byte comparison detects intervening changes but is not a universal transaction against unrelated writers that do not share the lock: avoid concurrent manifest configuration operations.

The verified remote commit is recorded in the audit/result. This does not pin future deployments to that commit; branches can advance. Revalidate the commit before any later deployment. Audit completion failure after replacement is returned as `audit_completion_failed=true` with a successful configured status; read back the record rather than blindly retrying.

No checkout, merge, build, container restart, deploy, migration, volume or integration configuration changes occur. This function does not synchronize another connector's registry. Read back each registry independently, and use only a reviewed project-scoped synchronization operation if required.

## Validation

Run `python -m unittest discover -s connector-v5 -p test_manifest_branch_configure.py -v`. Tests use temporary files and mocked Git operations; no production or network access is needed.

## Activation gate

The startup patch now explicitly accepts both known baselines (the generic 0.5.11 runner and the 0.5.12 filesystem-backup baseline). Unknown or ambiguous versions and missing runner anchors still fail closed. This adjustment was explicitly authorized for publication in this draft PR, without running the existing live Marketing test.

Validation: the composed runtime compiles; 14 of 15 standard-library tests pass. The existing controlled-operations regression fails because it expects the HeyGen import mapping to be absent, while that mapping is already present in the base. This PR does not change that credential policy or waive its failing test.

Before activation, resolve the legacy policy/test mismatch and verify actual FastMCP registration and behavior in an isolated environment with the declared dependencies. Dependency installation was unavailable in the preparation environment, so actual FastMCP registration was not tested. Do not treat source composition checks as an end-to-end runtime pass.

No live Marketing test, connector deployment or application deployment was performed. The official project registry has not been updated by this PR.

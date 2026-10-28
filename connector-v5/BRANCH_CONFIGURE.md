# Official branch configuration

`project_manifest_branch_configure` updates only `repository.branch` of an existing project manifest. It requires `confirm="EXECUTAR"`, the expected current branch, the destination branch, and its expected 40-character remote commit. It checks the registered GitHub repository with `git ls-remote`, without fetching or changing the checkout.

The operation preserves unknown manifest fields, creates an exclusive backup with mode 0600, records prepared/completed audit events, and replaces the JSON atomically. A per-project advisory lock serializes calls to this operation. The final byte comparison detects intervening changes but is not a universal transaction against unrelated writers that do not share the lock: avoid concurrent manifest configuration operations.

The verified remote commit is recorded in the audit/result. This does not pin future deployments to that commit; branches can advance. Revalidate the commit before any later deployment. Audit completion failure after replacement is returned as `audit_completion_failed=true` with a successful configured status; read back the record rather than blindly retrying.

No checkout, merge, build, container restart, deploy, migration, volume or integration configuration changes occur. This function does not synchronize another connector's registry. Read back each registry independently, and use only a reviewed project-scoped synchronization operation if required.

## Validation

Run `python -m unittest discover -s connector-v5 -p test_manifest_branch_configure.py -v`. Tests use temporary files and mocked Git operations; no production or network access is needed.

## Activation gate

This change is prepared against commit `5007237198c392fbbabb3d78b19c24100e2f1d97`. The pre-existing startup composition in that baseline fails before registration: `marketing_live_patch_version_match_count:0` (main.py declares 0.5.12 while the startup patch expects the generic 0.5.11 runner). Do not deploy this branch as-is. Reconcile the baseline, run the existing controlled-operations suite and verify actual MCP registration in an isolated environment before activation. These checks are not replaced by the nine isolated tests.

No connector or application deployment was performed while preparing this change.

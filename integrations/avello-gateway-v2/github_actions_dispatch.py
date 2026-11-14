"""Fail-closed GitHub Actions workflow dispatch adapter, NOT registered as MCP tool.

Requires a separately authorized service identity with GitHub Actions:write.
No arbitrary repository, ref, workflow, or workflow inputs are accepted.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

REPOSITORY = "cschibelsky-star/JARVIS"
BRANCH = "chore/via-android-118-structure-audit-20261113"
WORKFLOW = "via-android-118-isolated-validation.yml"
API = "https://api.github.com"
MAX_RESPONSE = 4096


class DispatchError(Exception):
    """Sanitized failure without secrets or response bodies."""


def validate_request(repository: str, workflow: str, ref: str, inputs: dict | None = None) -> None:
    if repository != REPOSITORY or workflow != WORKFLOW or ref != BRANCH:
        raise DispatchError("target_not_allowed")
    if inputs not in (None, {}):
        raise DispatchError("inputs_not_allowed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def dispatch(repository: str, workflow: str, ref: str, inputs: dict | None = None) -> dict:
    validate_request(repository, workflow, ref, inputs)
    token = os.getenv("VIA_GITHUB_ACTIONS_DISPATCH_TOKEN", "")
    if not token:
        raise DispatchError("credential_not_configured")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,512}", token):
        raise DispatchError("credential_invalid_format")
    url = f"{API}/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/dispatches"
    body = json.dumps({"ref": BRANCH}, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "vitrine-actions-dispatch-guard",
        },
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as response:
            status = response.status
            response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        raise DispatchError(f"github_http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise DispatchError("github_unreachable") from None
    if status != 204:
        raise DispatchError(f"github_unexpected_status_{status}")
    return {"status": "accepted_not_verified", "repository": REPOSITORY,
            "workflow": WORKFLOW, "ref": BRANCH,
            "next": "lookup_workflow_run_by_branch_and_dispatch_time"}

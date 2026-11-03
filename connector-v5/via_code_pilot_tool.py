"""Constrained MCP action for one Claude programming experiment in the isolated Roteia Lab.

No generic shell, no arbitrary model/prompt/script, no production target.
The Node script owns a durable single-use latch before upstream egress.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ID = "roteia-ai-lab"
EXPERIMENT = "VIA-CODE-01"
BRANCH = "feature/lab-bootstrap-v040-20261102"
COMPOSE = "compose.hml.yml"
SERVICE = "roteia-ai-lab"
APPROVAL = "EXECUTAR_VIA_CODE_01"
MAX_OUTPUT_CHARS = 16000
VALID_CODE = re.compile(r"^[a-zA-Z0-9_-]{3,128}$")


# A fixed read-only Node script run inside the already-running HML container.
# No docker inspect, log scraping, generic shell, network, credentials or mutation.
READONLY_DIAGNOSTIC_JS = r"""
import { DatabaseSync } from 'node:sqlite';
import { existsSync, accessSync, constants } from 'node:fs';
const dbPath = '/lab/data/finance.sqlite';
let writable = false;
try { accessSync('/lab/data', constants.W_OK); accessSync(dbPath, constants.W_OK); writable = true; } catch {}
const result = {
  experiment: 'VIA-CODE-01',
  databaseExists: existsSync(dbPath),
  sqliteWriteAccess: writable,
  credentialPresent: Boolean(process.env.ROTEIA_API_KEY),
  scriptPresent: existsSync('/lab/scripts/via-code-pilot.js'),
  tableExists: false,
  attemptRecorded: false,
  record: null,
};
if (result.databaseExists) {
  const db = new DatabaseSync(dbPath, { readOnly: true });
  try {
    const table = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='via_code_pilot'"
    ).get();
    result.tableExists = Boolean(table);
    if (table) {
      const row = db.prepare(
        "SELECT experiment, run_id, status, request_id, http_status, " +
        "reported_cost_brl, error_code, started_at, finished_at " +
        "FROM via_code_pilot WHERE experiment=?"
      ).get('VIA-CODE-01');
      result.attemptRecorded = Boolean(row);
      result.record = row || null;
    }
  } finally { db.close(); }
}
process.stdout.write(JSON.stringify(result));
"""


def diagnose_readonly(*, project_id: str, experiment_id: str,
                      resolve_project, runner=subprocess.run,
                      expected_workspace=Path("/srv/projects/roteia-ai-lab")) -> dict[str, Any]:
    """Fixed HML SQLite metadata probe: no provider requests or DB writes."""
    if project_id != PROJECT_ID or experiment_id != EXPERIMENT:
        return {"ok": False, "error": "experiment_or_project_not_allowed"}
    try:
        manifest, workspace, repository = resolve_project(PROJECT_ID)
        workspace = Path(workspace).resolve()
        repository = Path(repository).resolve()
        if (workspace != Path(expected_workspace).resolve()
                or repository != workspace / "repository"
                or manifest.get("id") != PROJECT_ID
                or manifest.get("docker", {}).get("compose_file") != COMPOSE
                or manifest.get("docker", {}).get("project_name") != PROJECT_ID
                or manifest.get("domains", {}).get("production")):
            return {"ok": False, "error": "readonly_scope_mismatch"}
        argv = ["docker", "exec", "-u", "node", "roteia_ai_lab_hml",
                "node", "--input-type=module", "-e", READONLY_DIAGNOSTIC_JS]
        completed = runner(argv, cwd=str(repository), capture_output=True,
                           text=True, timeout=15, check=False)
        if completed.returncode != 0:
            return {"ok": False, "error": "readonly_probe_unavailable"}
        data = json.loads(completed.stdout.strip())
        if not isinstance(data, dict) or data.get("experiment") != EXPERIMENT:
            return {"ok": False, "error": "readonly_probe_invalid_response"}
        record = data.get("record") if isinstance(data.get("record"), dict) else None
        safe_record = None
        if record:
            safe_record = {k: record.get(k) for k in (
                "experiment", "run_id", "status", "request_id", "http_status",
                "reported_cost_brl", "error_code", "started_at", "finished_at")}
        return {
            "ok": True,
            "experiment": EXPERIMENT,
            "databaseExists": data.get("databaseExists") is True,
            "sqliteWriteAccess": data.get("sqliteWriteAccess") is True,
            "credentialPresent": data.get("credentialPresent") is True,
            "scriptPresent": data.get("scriptPresent") is True,
            "tableExists": data.get("tableExists") is True,
            "attemptRecorded": data.get("attemptRecorded") is True,
            "record": safe_record,
            "readOnly": True,
            "upstreamCalled": False,
        }
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return {"ok": False, "error": "readonly_probe_failed"}



def execute_once(*, project_id: str, experiment_id: str, confirm: str,
                 resolve_project, runner=subprocess.run, audit=None,
                 expected_workspace=Path("/srv/projects/roteia-ai-lab")) -> dict[str, Any]:
    """Narrow executor: inputs select no paths, arguments or credentials."""
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required"}
    if project_id != PROJECT_ID or experiment_id != EXPERIMENT:
        return {"ok": False, "error": "experiment_or_project_not_allowed"}
    try:
        manifest, workspace, repository = resolve_project(PROJECT_ID)
        workspace = Path(workspace).resolve()
        repository = Path(repository).resolve()
        if workspace != Path(expected_workspace).resolve():
            return {"ok": False, "error": "workspace_mismatch"}
        if repository != workspace / "repository":
            return {"ok": False, "error": "repository_mismatch"}
        if manifest.get("id") != PROJECT_ID:
            return {"ok": False, "error": "manifest_id_mismatch"}
        if manifest.get("repository", {}).get("branch") != BRANCH:
            return {"ok": False, "error": "branch_mismatch"}
        docker = manifest.get("docker", {})
        if docker.get("compose_file") != COMPOSE or docker.get("project_name") != PROJECT_ID:
            return {"ok": False, "error": "compose_manifest_mismatch"}
        if manifest.get("domains", {}).get("production"):
            return {"ok": False, "error": "production_target_not_allowed"}
        compose = (repository / COMPOSE).resolve()
        script = (repository / "scripts/via-code-pilot.js").resolve()
        if compose != repository / COMPOSE or script != repository / "scripts/via-code-pilot.js":
            return {"ok": False, "error": "path_mismatch"}
        if not compose.is_file() or not script.is_file():
            return {"ok": False, "error": "experiment_assets_missing"}
        runtime = (workspace / ".env.runtime").resolve()
        if runtime != workspace / ".env.runtime" or not runtime.is_file():
            return {"ok": False, "error": "runtime_file_missing"}
        # Check branch/tree without fetching or altering anything. Refuse unreviewed local edits.
        for args, expected in (
            (["git", "branch", "--show-current"], BRANCH),
            (["git", "status", "--porcelain", "--untracked-files=no"], ""),
        ):
            checked = runner(args, cwd=str(repository), capture_output=True, text=True,
                             timeout=12, check=False)
            if checked.returncode != 0 or checked.stdout.strip() != expected:
                return {"ok": False, "error": "git_preflight_failed"}
        argv = [
            "docker", "compose", "-p", PROJECT_ID, "-f", COMPOSE,
            "run", "--rm", "--no-deps",
            "-e", "ROTEIA_PAID_ENABLED=true",
            "-e", "LAB_CODE_PILOT_APPROVAL=" + APPROVAL,
            "--entrypoint", "node", SERVICE, "scripts/via-code-pilot.js",
        ]
        # Never forward the user's prompt, arbitrary commands, or the secret through MCP arguments.
        # The provider credential is read server-side from the existing Compose runtime env file.
        result = runner(argv, cwd=str(repository), capture_output=True, text=True,
                        timeout=95, check=False)
        try:
            raw = json.loads(result.stdout.strip())
        except (ValueError, TypeError):
            raw = None
        if not isinstance(raw, dict) or raw.get("experiment") != EXPERIMENT:
            response = {"ok": False, "error": "unverified_result_charge_possible",
                        "experiment": EXPERIMENT, "exitCode": result.returncode}
        else:
            answer = raw.get("answer")
            if not isinstance(answer, str):
                answer = None
            if answer is not None:
                answer = answer[:MAX_OUTPUT_CHARS]
                # Do not expose accidental provider API keys in model output.
                answer = re.sub(r"rt-live-[A-Za-z0-9_-]{12,}", "[redacted]", answer)
            request_id = raw.get("requestId")
            if not isinstance(request_id, str) or not VALID_CODE.fullmatch(request_id):
                request_id = None
            response = {
                "ok": bool(result.returncode == 0 and raw.get("ok") and answer),
                "experiment": EXPERIMENT, "model": str(raw.get("model") or "")[:100],
                "runId": str(raw.get("runId") or "")[:100],
                "requestId": request_id,
                "status": "response_received" if result.returncode == 0 and raw.get("ok") and answer else "charge_unknown",
                "reportedCostBRL": raw.get("reportedCostBRL") if isinstance(raw.get("reportedCostBRL"), str) and
                   re.fullmatch(r"(0|[1-9][0-9]{0,7})(\.[0-9]{1,24})?", raw["reportedCostBRL"]) else None,
                "inputTokens": raw.get("inputTokens") if type(raw.get("inputTokens")) is int else None,
                "outputTokens": raw.get("outputTokens") if type(raw.get("outputTokens")) is int else None,
                "finishReason": str(raw.get("finishReason") or "")[:40],
                "answer": answer,
                "error": str(raw.get("error") or "")[:120] if not (result.returncode == 0 and raw.get("ok")) else None,
            }
        if audit is not None:
            # Persist metadata only, never the generated answer or any credentials.
            audit("project_roteia_via_code_pilot_execute",
                  {"project_id": PROJECT_ID, "experiment": EXPERIMENT},
                  {"ok": response["ok"], "status": response.get("status", response.get("error"))})
        return response
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "executor_timeout_charge_possible", "experiment": EXPERIMENT}
    except (OSError, ValueError, TypeError, KeyError):
        return {"ok": False, "error": "executor_preflight_or_transport_failed", "experiment": EXPERIMENT}


def register(mcp, core):
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def project_roteia_via_code_pilot_execute(
        project_id: str, experiment_id: str, confirm: str = ""
    ) -> dict[str, Any]:
        return execute_once(project_id=project_id, experiment_id=experiment_id, confirm=confirm,
                            resolve_project=core._project_paths, audit=core._audit)
    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def project_roteia_via_code_pilot_diagnose(
        project_id: str, experiment_id: str
    ) -> dict[str, Any]:
        return diagnose_readonly(
            project_id=project_id, experiment_id=experiment_id,
            resolve_project=core._project_paths,
        )
    return project_roteia_via_code_pilot_execute

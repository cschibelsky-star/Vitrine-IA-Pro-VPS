from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import branding_entrypoint  # noqa: F401 - registers existing Super tools
import main

N8N_CONTAINER = "n8n-main"
FLOW_BACKUP_ROOT = Path("/srv/projects/vitrine-flow-control/backups").resolve()


def _n8n_run(args: list[str], timeout: int = 120) -> dict[str, Any]:
    return main._run(
        ["docker", "exec", N8N_CONTAINER, "n8n", *args],
        Path("/"),
        timeout=timeout,
    )


@main.mcp.tool(
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
def n8n_cli_probe() -> dict[str, Any]:
    version = _n8n_run(["--version"], timeout=30)
    help_result = _n8n_run(["--help"], timeout=30)

    result = {
        "ok": bool(version.get("ok") and help_result.get("ok")),
        "container": N8N_CONTAINER,
        "version": str(version.get("stdout", "")).strip(),
        "help": str(help_result.get("stdout", ""))[-12000:],
        "stderr": str(help_result.get("stderr", ""))[-2000:],
    }

    main._audit(
        "n8n.cli_probe",
        {},
        {"ok": result["ok"], "version": result["version"]},
    )
    return result


@main.mcp.tool(
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
def n8n_workflow_list() -> dict[str, Any]:
    result = _n8n_run(["list:workflow"], timeout=60)

    response = {
        "ok": result.get("ok", False),
        "container": N8N_CONTAINER,
        "stdout": str(result.get("stdout", ""))[-30000:],
        "stderr": str(result.get("stderr", ""))[-4000:],
        "exit_code": result.get("exit_code"),
    }

    main._audit(
        "n8n.workflow_list",
        {},
        {
            "ok": response["ok"],
            "exit_code": response.get("exit_code"),
        },
    )
    return response


@main.mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": False}
)
def n8n_workflow_export_all(confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {
            "ok": False,
            "error": "confirmation_required",
            "required": "EXECUTAR",
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        FLOW_BACKUP_ROOT / f"n8n-workflows-{stamp}.json"
    ).resolve()

    try:
        destination.relative_to(FLOW_BACKUP_ROOT)
    except ValueError:
        return {"ok": False, "error": "backup_path_blocked"}

    FLOW_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    temp_container = f"/tmp/n8n-workflows-{stamp}.json"

    exported = _n8n_run(
        [
            "export:workflow",
            "--all",
            "--pretty",
            f"--output={temp_container}",
        ],
        timeout=180,
    )

    if not exported.get("ok"):
        response = {
            "ok": False,
            "error": "n8n_export_failed",
            "detail": exported,
        }
        main._audit(
            "n8n.workflow_export_all",
            {},
            {"ok": False, "error": response["error"]},
        )
        return response

    copied = main._run(
        [
            "docker",
            "cp",
            f"{N8N_CONTAINER}:{temp_container}",
            str(destination),
        ],
        Path("/"),
        timeout=120,
    )

    main._run(
        [
            "docker",
            "exec",
            N8N_CONTAINER,
            "rm",
            "-f",
            temp_container,
        ],
        Path("/"),
        timeout=30,
    )

    if not copied.get("ok") or not destination.is_file():
        response = {
            "ok": False,
            "error": "n8n_export_copy_failed",
            "detail": copied,
        }
        main._audit(
            "n8n.workflow_export_all",
            {},
            {"ok": False, "error": response["error"]},
        )
        return response

    response = {
        "ok": True,
        "status": "exported",
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "container": N8N_CONTAINER,
    }

    main._audit("n8n.workflow_export_all", {}, response)
    return response


main.VERSION = "0.4.0-n8n-flow-control"


if __name__ == "__main__":
    main.mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
    )

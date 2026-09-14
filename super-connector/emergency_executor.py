from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

CANDIDATE = os.getenv("SUPER_CANDIDATE_CONTAINER", "vitrine_super_connector_candidate").strip()
if not CANDIDATE or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in CANDIDATE):
    raise RuntimeError("invalid_candidate_container")
CANDIDATE_IMAGE = os.getenv("SUPER_CANDIDATE_IMAGE", "vitrine-super-centro-operacional-candidate-super_connector:latest").strip()
if not CANDIDATE_IMAGE or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:/@-" for ch in CANDIDATE_IMAGE):
    raise RuntimeError("invalid_candidate_image")

ALLOWED = {
    "health": ["docker", "inspect", "--format", "{{json .State}}", CANDIDATE],
    "logs": ["docker", "logs", "--tail", "200", CANDIDATE],
    "stop": ["docker", "stop", "--time", "20", CANDIDATE],
    "start": ["docker", "start", CANDIDATE],
}


def _candidate_run(image: str) -> list[str]:
    return [
        "docker", "run", "-d", "--name", CANDIDATE, "--restart", "unless-stopped",
        "-p", "127.0.0.1:8870:8000",
        "-e", "SUPER_REGISTRY_ROOT=/data/registry/projects",
        "-e", "SUPER_LEGACY_V5_REGISTRY_ROOT=/legacy-v5-manifests",
        "-e", "SUPER_WORKSPACE_ROOTS=/srv/projects,/srv/tvsumare",
        "-e", "SUPER_AUDIT_LOG=/var/log/vitrine-super-ops/audit.jsonl",
        "-e", "SUPER_PHP_RUNNER_IMAGE=vitrine-super-php-runner:0.1",
        "-e", "GIT_AUTHOR_NAME=cschibelsky-star",
        "-e", "GIT_AUTHOR_EMAIL=cschibelsky@gmail.com",
        "-e", "GIT_COMMITTER_NAME=cschibelsky-star",
        "-e", "GIT_COMMITTER_EMAIL=cschibelsky@gmail.com",
        "-v", "/srv/connectors/vitrine-super-ops/registry:/data/registry/projects:rw",
        "-v", "/srv/connectors/vitrine-vps-mcp/project-manifests:/legacy-v5-manifests:ro",
        "-v", "/srv/projects:/srv/projects:rw",
        "-v", "/srv/Backup zip:/backup-archives:ro",
        "-v", "/srv/tvsumare:/srv/tvsumare:rw",
        "-v", "/var/log/vitrine-super-ops:/var/log/vitrine-super-ops:rw",
        "-v", "/root/.ssh:/root/.ssh:ro",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "--network", "vitrine_net",
        "--label", "traefik.enable=true",
        "--label", "traefik.docker.network=n8n-traefik_app_network",
        "--label", "traefik.http.routers.super-mcp.rule=Host(`super-mcp.vitrineiapro.com.br`)",
        "--label", "traefik.http.routers.super-mcp.entrypoints=websecure",
        "--label", "traefik.http.routers.super-mcp.tls=true",
        "--label", "traefik.http.routers.super-mcp.tls.certresolver=le",
        "--label", "traefik.http.services.super-mcp.loadbalancer.server.port=8000",
        "--health-cmd", "python -c \"import socket; s=socket.create_connection(('127.0.0.1',8000),3); s.close()\"",
        "--health-interval", "10s", "--health-timeout", "5s", "--health-retries", "8", "--health-start-period", "10s",
        image,
    ]


def _replace_super(confirm: str) -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    previous = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", CANDIDATE], text=True, capture_output=True, timeout=30, check=False)
    previous_image = previous.stdout.strip() if previous.returncode == 0 else ""
    subprocess.run(["docker", "stop", "--time", "20", CANDIDATE], text=True, capture_output=True, timeout=60, check=False)
    subprocess.run(["docker", "rm", "-f", CANDIDATE], text=True, capture_output=True, timeout=60, check=False)
    created = subprocess.run(_candidate_run(CANDIDATE_IMAGE), text=True, capture_output=True, timeout=120, check=False)
    if created.returncode == 0:
        subprocess.run(["docker", "network", "connect", "n8n-traefik_app_network", CANDIDATE], text=True, capture_output=True, timeout=30, check=False)
        return {"ok": True, "status": "replaced", "candidate": CANDIDATE}
    if previous_image:
        subprocess.run(_candidate_run(previous_image), text=True, capture_output=True, timeout=120, check=False)
        subprocess.run(["docker", "network", "connect", "n8n-traefik_app_network", CANDIDATE], text=True, capture_output=True, timeout=30, check=False)
    return {"ok": False, "error": "replace_super_failed", "rollback_attempted": bool(previous_image)}


def run(operation: str, confirm: str = "") -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    if op == "replace-super":
        return _replace_super(confirm)
    if op not in ALLOWED:
        return {"ok": False, "error": "operation_not_allowed", "allowed": sorted([*ALLOWED, "replace-super"])}
    if op not in {"health", "logs"} and confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}

    try:
        proc = subprocess.run(
            ALLOWED[op],
            cwd=str(Path("/")),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "operation": op, "candidate": CANDIDATE}
    except OSError as exc:
        return {"ok": False, "error": type(exc).__name__, "operation": op, "candidate": CANDIDATE}

    return {
        "ok": proc.returncode == 0,
        "operation": op,
        "candidate": CANDIDATE,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-8000:],
    }


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else "health"
    confirm = sys.argv[2] if len(sys.argv) > 2 else ""
    result = run(operation, confirm)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

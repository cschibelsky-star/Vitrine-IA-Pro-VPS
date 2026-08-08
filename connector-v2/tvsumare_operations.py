from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tvsumare")

TV_ROOT = Path(os.getenv("TVSUMARE_ROOT", "/srv/tvsumare")).resolve()
TV_BACKUP_ROOT = Path(os.getenv("TVSUMARE_BACKUP_ROOT", "/srv/backups/tvsumare")).resolve()
NGINX_CONF_ROOT = Path(os.getenv("NGINX_CONF_ROOT", "/srv/vitrine/docker/nginx/conf.d")).resolve()
NGINX_HTML_ROOT = Path(os.getenv("NGINX_HTML_ROOT", "/srv/vitrine/docker/nginx/html")).resolve()
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("TVSUMARE_OPS_TIMEOUT", "1200"))

AUTO_ROOTS = (TV_ROOT, TV_BACKUP_ROOT, NGINX_CONF_ROOT, NGINX_HTML_ROOT)
BLOCKED_NAMES = {".env", ".env.production", ".env.local", "id_rsa", "id_ed25519", "privkey.pem"}


class PathRequest(BaseModel):
    path: str = "."


class WriteRequest(BaseModel):
    path: str
    content: str
    backup: bool = True


class VhostRequest(BaseModel):
    domain: str
    upstream: str = "tvsumare_web:80"
    homologation: bool = True


class CommandResult(BaseModel):
    ok: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "tvsumare",
        "action": action,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_allowed(path: str, root: Path = TV_ROOT) -> Path:
    candidate = (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=403, detail="path_outside_allowed_root")
    if any(part in BLOCKED_NAMES for part in candidate.parts):
        raise HTTPException(status_code=403, detail="sensitive_path_blocked")
    return candidate


def run(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd or TV_ROOT),
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
            env={
                "PATH": os.getenv("PATH", ""),
                "HOME": "/root",
                "LC_ALL": "C.UTF-8",
            },
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-20000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exit_code": 124, "stdout": exc.stdout or "", "stderr": "timeout"}


def backup_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    relative = path.name
    destination = TV_BACKUP_ROOT / "files" / f"{relative}.bak-{stamp}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return str(destination)


@router.get("/health", dependencies=[Depends(auth)])
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "tv_root": str(TV_ROOT),
        "tv_root_exists": TV_ROOT.exists(),
        "tv_root_writable": TV_ROOT.exists() and os.access(TV_ROOT, os.W_OK),
        "backup_root": str(TV_BACKUP_ROOT),
        "nginx_conf_root": str(NGINX_CONF_ROOT),
    }


@router.post("/workspace/create", dependencies=[Depends(auth)])
def workspace_create() -> dict[str, Any]:
    directories = [
        TV_ROOT / "repository",
        TV_ROOT / "releases",
        TV_ROOT / "shared" / "data",
        TV_ROOT / "shared" / "uploads",
        TV_ROOT / "shared" / "videos",
        TV_ROOT / "shared" / "logs",
        TV_ROOT / "shared" / "secrets",
        TV_ROOT / "scripts",
        TV_BACKUP_ROOT,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    result = {"ok": True, "directories": [str(item) for item in directories]}
    audit("workspace_create", {}, result)
    return result


@router.post("/write", dependencies=[Depends(auth)])
def write_file(req: WriteRequest) -> dict[str, Any]:
    path = resolve_allowed(req.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(path) if req.backup else None
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(req.content, encoding="utf-8")
    temporary.replace(path)
    result = {"ok": True, "path": str(path), "backup": backup, "size": len(req.content.encode("utf-8"))}
    audit("write_file", {"path": req.path, "backup": req.backup}, result)
    return result


@router.post("/git/status", dependencies=[Depends(auth)])
def git_status() -> dict[str, Any]:
    repository = TV_ROOT / "repository"
    result = run(["git", "status", "--short", "--branch"], repository)
    audit("git_status", {}, result)
    return result


@router.post("/tests/php-lint", dependencies=[Depends(auth)])
def php_lint() -> dict[str, Any]:
    repository = TV_ROOT / "repository"

    # Use the exact PHP runtime image already running for TV Sumaré, but mount
    # the current repository read-only. This validates pending source changes
    # before rebuild instead of linting the stale code baked into tvsumare_web.
    image_result = run(
        ["docker", "inspect", "--format", "{{.Config.Image}}", "tvsumare_web"],
        repository,
    )
    if not image_result["ok"]:
        result = {
            "ok": False,
            "exit_code": image_result["exit_code"],
            "stdout": image_result["stdout"],
            "stderr": "Nao foi possivel identificar a imagem do container tvsumare_web. " + image_result["stderr"],
        }
        audit("php_lint", {"runtime": "tvsumare_web"}, result)
        return result

    image = image_result["stdout"].strip()
    if not image:
        result = {"ok": False, "exit_code": 125, "stdout": "", "stderr": "Imagem do tvsumare_web nao identificada."}
        audit("php_lint", {"runtime": "tvsumare_web"}, result)
        return result

    lint_script = (
        "set -eu; "
        "files=$(find /lint -type f -name '*.php' -not -path '/lint/vendor/*' -not -path '/lint/.git/*'); "
        "if [ -z \"$files\" ]; then echo 'Nenhum arquivo PHP encontrado.'; exit 0; fi; "
        "find /lint -type f -name '*.php' -not -path '/lint/vendor/*' -not -path '/lint/.git/*' -print0 "
        "| xargs -0 -n1 php -l"
    )
    result = run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m",
            "--entrypoint",
            "sh",
            "-v",
            f"{repository}:/lint:ro",
            image,
            "-lc",
            lint_script,
        ],
        repository,
    )
    result["runtime_image"] = image
    result["source_mount"] = f"{repository}:/lint:ro"
    audit("php_lint", {"runtime": "temporary_container", "image": image}, result)
    return result


@router.post("/docker/build", dependencies=[Depends(auth)])
def docker_build() -> dict[str, Any]:
    repository = TV_ROOT / "repository"
    result = run(["docker", "compose", "-f", "docker-compose.vps.yml", "build"], repository)
    audit("docker_build", {}, result)
    return result


@router.post("/docker/up", dependencies=[Depends(auth)])
def docker_up() -> dict[str, Any]:
    repository = TV_ROOT / "repository"
    result = run(["docker", "compose", "-f", "docker-compose.vps.yml", "up", "-d"], repository)
    audit("docker_up", {}, result)
    return result


@router.post("/nginx/vhost", dependencies=[Depends(auth)])
def create_vhost(req: VhostRequest) -> dict[str, Any]:
    if not req.domain or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in req.domain.lower()):
        raise HTTPException(status_code=422, detail="invalid_domain")
    name = "tv-sumare-hml.conf" if req.homologation else "tv-sumare.conf"
    path = NGINX_CONF_ROOT / name
    backup = backup_file(path)
    content = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {req.domain};

    location /.well-known/acme-challenge/ {{
        root /usr/share/nginx/html;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {req.domain};

    ssl_certificate /etc/letsencrypt/live/{req.domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{req.domain}/privkey.pem;

    client_max_body_size 100M;

    location / {{
        proxy_pass http://{req.upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    test = run(["docker", "exec", "vitrine_nginx", "nginx", "-t"], TV_ROOT)
    if not test["ok"]:
        if backup:
            shutil.copy2(backup, path)
        else:
            path.unlink(missing_ok=True)
        audit("create_vhost_failed", {"domain": req.domain}, test)
        raise HTTPException(status_code=422, detail={"message": "nginx_test_failed", "result": test})
    reload_result = run(["docker", "exec", "vitrine_nginx", "nginx", "-s", "reload"], TV_ROOT)
    result = {"ok": reload_result["ok"], "path": str(path), "backup": backup, "test": test, "reload": reload_result}
    audit("create_vhost", {"domain": req.domain, "upstream": req.upstream}, result)
    return result


@router.post("/release/zip", dependencies=[Depends(auth)])
def create_release_zip() -> dict[str, Any]:
    repository = TV_ROOT / "repository"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = TV_ROOT / "releases" / f"TVSUMARE_RELEASE_{stamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    excluded = {".git", ".env", "data", "uploads", "videos", "logs", "vendor", "node_modules"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in repository.rglob("*"):
            relative = path.relative_to(repository)
            if any(part in excluded for part in relative.parts):
                continue
            if path.is_file():
                archive.write(path, relative.as_posix())
    result = {"ok": True, "path": str(target), "size": target.stat().st_size}
    audit("create_release_zip", {}, result)
    return result

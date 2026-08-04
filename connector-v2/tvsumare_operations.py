from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/tvsumare")

TV_ROOT = Path(os.getenv("TVSUMARE_ROOT", "/srv/tvsumare")).resolve()
TV_BACKUP_ROOT = Path(os.getenv("TVSUMARE_BACKUP_ROOT", "/srv/backups/tvsumare")).resolve()
NGINX_CONF_ROOT = Path(os.getenv("NGINX_CONF_ROOT", "/srv/vitrine/docker/nginx/conf.d")).resolve()
NGINX_HTML_ROOT = Path(os.getenv("NGINX_HTML_ROOT", "/srv/vitrine/docker/nginx/html")).resolve()
SSL_ROOT = Path(os.getenv("VITRINE_SSL_ROOT", "/srv/vitrine/ssl")).resolve()
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("TVSUMARE_OPS_TIMEOUT", "1200"))
CERTBOT_IMAGE = os.getenv("CERTBOT_IMAGE", "certbot/certbot:latest")

AUTO_ROOTS = (TV_ROOT, TV_BACKUP_ROOT, NGINX_CONF_ROOT, NGINX_HTML_ROOT, SSL_ROOT)
BLOCKED_NAMES = {".env", ".env.production", ".env.local", "id_rsa", "id_ed25519", "privkey.pem"}


class WriteRequest(BaseModel):
    path: str
    content: str
    backup: bool = True


class VhostRequest(BaseModel):
    domain: str
    upstream: str = "tvsumare_web:80"
    homologation: bool = True


class CertificateRequest(BaseModel):
    domain: str
    email: str


class PublicationRequest(BaseModel):
    domain: str
    upstream: str = "tvsumare_web:80"
    email: str


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


def valid_domain(domain: str) -> str:
    normalized = domain.strip().lower().rstrip(".")
    if not normalized or len(normalized) > 253:
        raise HTTPException(status_code=422, detail="invalid_domain")
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in normalized):
        raise HTTPException(status_code=422, detail="invalid_domain")
    labels = normalized.split(".")
    if len(labels) < 2 or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise HTTPException(status_code=422, detail="invalid_domain")
    return normalized


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
    destination = TV_BACKUP_ROOT / "files" / f"{path.name}.bak-{stamp}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return str(destination)


def restore_file(path: Path, backup: str | None) -> None:
    if backup:
        shutil.copy2(backup, path)
    else:
        path.unlink(missing_ok=True)


def certificate_files(domain: str) -> dict[str, Path]:
    base = SSL_ROOT / "live" / domain
    return {
        "cert": base / "cert.pem",
        "chain": base / "chain.pem",
        "fullchain": base / "fullchain.pem",
        "privkey": base / "privkey.pem",
    }


def certificate_ready(domain: str) -> tuple[bool, dict[str, str]]:
    files = certificate_files(domain)
    details: dict[str, str] = {}
    ready = True
    for name, path in files.items():
        try:
            resolved = path.resolve(strict=True)
            details[name] = str(resolved)
            if not resolved.is_file() or resolved.stat().st_size == 0:
                ready = False
        except FileNotFoundError:
            details[name] = "missing"
            ready = False
    return ready, details


def resolve_dns(domain: str) -> list[str]:
    try:
        answers = socket.getaddrinfo(domain, 80, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail={"message": "dns_not_resolved", "error": str(exc)}) from exc
    return sorted({item[4][0] for item in answers})


def write_http_challenge_vhost(domain: str, upstream: str) -> tuple[Path, str | None]:
    path = NGINX_CONF_ROOT / "tv-sumare-hml.conf"
    backup = backup_file(path)
    content = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    location ^~ /.well-known/acme-challenge/ {{
        root /usr/share/nginx/html;
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path, backup


def write_https_vhost(domain: str, upstream: str) -> tuple[Path, str | None]:
    path = NGINX_CONF_ROOT / "tv-sumare-hml.conf"
    backup = backup_file(path)
    content = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {domain};

    location ^~ /.well-known/acme-challenge/ {{
        root /usr/share/nginx/html;
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:TVSumareSSL:10m;
    ssl_session_tickets off;

    client_max_body_size 100M;

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 30s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path, backup


def nginx_test() -> dict[str, Any]:
    return run(["docker", "exec", "vitrine_nginx", "nginx", "-t"], TV_ROOT)


def nginx_reload() -> dict[str, Any]:
    return run(["docker", "exec", "vitrine_nginx", "nginx", "-s", "reload"], TV_ROOT)


def issue_certificate(domain: str, email: str) -> dict[str, Any]:
    SSL_ROOT.mkdir(parents=True, exist_ok=True)
    NGINX_HTML_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{SSL_ROOT}:/etc/letsencrypt",
        "-v",
        f"{NGINX_HTML_ROOT}:/var/www/certbot",
        CERTBOT_IMAGE,
        "certonly",
        "--webroot",
        "--webroot-path",
        "/var/www/certbot",
        "--domain",
        domain,
        "--email",
        email,
        "--agree-tos",
        "--non-interactive",
        "--no-eff-email",
        "--keep-until-expiring",
    ]
    result = run(command, TV_ROOT)
    ready, files = certificate_ready(domain)
    result["certificate_ready"] = ready
    result["files"] = files
    if result["ok"] and not ready:
        result["ok"] = False
        result["stderr"] = (result.get("stderr", "") + "\ncertificate_files_missing").strip()
    return result


@router.get("/health", dependencies=[Depends(auth)])
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "tv_root": str(TV_ROOT),
        "tv_root_exists": TV_ROOT.exists(),
        "tv_root_writable": TV_ROOT.exists() and os.access(TV_ROOT, os.W_OK),
        "backup_root": str(TV_BACKUP_ROOT),
        "nginx_conf_root": str(NGINX_CONF_ROOT),
        "ssl_root": str(SSL_ROOT),
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
    command = ["docker", "run", "--rm", "-v", f"{repository}:/app:ro", "-w", "/app", "php:8.3-cli", "sh", "-lc", "find . -type f -name '*.php' -not -path './vendor/*' -print0 | xargs -0 -n1 php -l"]
    result = run(command, repository)
    audit("php_lint", {}, result)
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


@router.post("/ssl/issue", dependencies=[Depends(auth)])
def ssl_issue(req: CertificateRequest) -> dict[str, Any]:
    domain = valid_domain(req.domain)
    if "@" not in req.email or len(req.email) > 254:
        raise HTTPException(status_code=422, detail="invalid_email")
    dns = resolve_dns(domain)
    result = issue_certificate(domain, req.email)
    result["dns"] = dns
    audit("ssl_issue", {"domain": domain, "email": req.email}, result)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail={"message": "certificate_issue_failed", "result": result})
    return result


@router.post("/nginx/vhost", dependencies=[Depends(auth)])
def create_vhost(req: VhostRequest) -> dict[str, Any]:
    domain = valid_domain(req.domain)
    ready, files = certificate_ready(domain)
    if not ready:
        raise HTTPException(status_code=422, detail={"message": "certificate_not_ready", "files": files})
    path, backup = write_https_vhost(domain, req.upstream)
    test = nginx_test()
    if not test["ok"]:
        restore_file(path, backup)
        audit("create_vhost_failed", {"domain": domain}, test)
        raise HTTPException(status_code=422, detail={"message": "nginx_test_failed", "result": test})
    reload_result = nginx_reload()
    result = {"ok": reload_result["ok"], "path": str(path), "backup": backup, "test": test, "reload": reload_result}
    audit("create_vhost", {"domain": domain, "upstream": req.upstream}, result)
    return result


@router.post("/publication/homologation", dependencies=[Depends(auth)])
def publish_homologation(req: PublicationRequest) -> dict[str, Any]:
    domain = valid_domain(req.domain)
    if "@" not in req.email or len(req.email) > 254:
        raise HTTPException(status_code=422, detail="invalid_email")
    dns = resolve_dns(domain)
    path, original_backup = write_http_challenge_vhost(domain, req.upstream)
    test_http = nginx_test()
    if not test_http["ok"]:
        restore_file(path, original_backup)
        audit("publish_homologation_failed", {"stage": "http_vhost", "domain": domain}, test_http)
        raise HTTPException(status_code=422, detail={"message": "http_vhost_invalid", "result": test_http})
    reload_http = nginx_reload()
    if not reload_http["ok"]:
        restore_file(path, original_backup)
        raise HTTPException(status_code=422, detail={"message": "http_vhost_reload_failed", "result": reload_http})

    cert = issue_certificate(domain, req.email)
    if not cert["ok"]:
        restore_file(path, original_backup)
        nginx_test()
        nginx_reload()
        audit("publish_homologation_failed", {"stage": "certificate", "domain": domain}, cert)
        raise HTTPException(status_code=422, detail={"message": "certificate_issue_failed", "result": cert})

    https_backup = backup_file(path)
    write_https_vhost(domain, req.upstream)
    test_https = nginx_test()
    if not test_https["ok"]:
        restore_file(path, https_backup or original_backup)
        nginx_test()
        nginx_reload()
        audit("publish_homologation_failed", {"stage": "https_vhost", "domain": domain}, test_https)
        raise HTTPException(status_code=422, detail={"message": "https_vhost_invalid", "result": test_https})

    reload_https = nginx_reload()
    checks: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=30, follow_redirects=True, verify=True) as client:
            for name, url in {
                "http": f"http://{domain}/",
                "https": f"https://{domain}/",
                "health": f"https://{domain}/health.php",
            }.items():
                response = client.get(url)
                checks[name] = {"status_code": response.status_code, "final_url": str(response.url)}
    except Exception as exc:
        restore_file(path, https_backup or original_backup)
        nginx_test()
        nginx_reload()
        failure = {"ok": False, "error": str(exc), "checks": checks}
        audit("publish_homologation_failed", {"stage": "public_checks", "domain": domain}, failure)
        raise HTTPException(status_code=422, detail={"message": "public_checks_failed", "result": failure}) from exc

    ok = reload_https["ok"] and checks.get("health", {}).get("status_code") == 200
    result = {
        "ok": ok,
        "domain": domain,
        "dns": dns,
        "certificate": cert,
        "nginx_test": test_https,
        "nginx_reload": reload_https,
        "checks": checks,
        "path": str(path),
    }
    audit("publish_homologation", {"domain": domain, "upstream": req.upstream}, result)
    if not ok:
        restore_file(path, https_backup or original_backup)
        nginx_test()
        nginx_reload()
        raise HTTPException(status_code=422, detail={"message": "publication_validation_failed", "result": result})
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

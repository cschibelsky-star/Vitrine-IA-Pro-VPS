from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

CONNECTOR_ID = "vitrine_ops"
CONNECTOR_DISPLAY_NAME = "Vitrine IA Pro — Centro Operacional"
CONNECTOR_VERSION = "2.1.0-stabilization.1"
PROJECT_MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests"))


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid_project_id")
    return value


def project_context(project_id: str) -> dict[str, Any]:
    project_id = _safe_project_id(project_id)
    path = (PROJECT_MANIFEST_ROOT / f"{project_id}.json").resolve()
    root = PROJECT_MANIFEST_ROOT.resolve()
    if root not in path.parents or not path.is_file():
        return {"ok": False, "error": "manifest_not_found", "project_id": project_id}
    data = json.loads(path.read_text(encoding="utf-8"))
    workspace = PurePosixPath(data["workspace_root"])
    repository = workspace / data.get("repository", {}).get("directory", "repository")
    docker = data.get("docker", {})
    deployment = data.get("deployment", {})
    return {
        "ok": True,
        "project_id": project_id,
        "name": data.get("name", project_id),
        "workspace_root": str(workspace),
        "repository_root": str(repository),
        "repository_url": data.get("repository", {}).get("url"),
        "branch": data.get("repository", {}).get("branch", "main"),
        "compose_file": docker.get("compose_file", "docker-compose.yml"),
        "docker_project": docker.get("project_name", project_id),
        "service": docker.get("service"),
        "backup_root": data.get("backup_root"),
        "homologation": deployment.get("homologation", {}),
        "production": deployment.get("production", {}),
    }


def _x509_identity(value: str) -> str:
    identity = str(value or "").strip().lower()
    if not identity or len(identity) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in identity):
        raise ValueError("invalid_x509_identity")
    return identity


def _x509_dir(identity: str) -> Path:
    root = Path(os.getenv("SUPER_X509_ROOT", "/data/x509")).resolve()
    path = (root / _x509_identity(identity)).resolve()
    if root not in path.parents:
        raise PermissionError("x509_path_blocked")
    return path


def workload_identity_x509_status(identity: str) -> dict[str, Any]:
    try:
        safe = _x509_identity(identity)
        path = _x509_dir(safe)
    except (ValueError, PermissionError) as exc:
        return {"ok": False, "error": str(exc)}
    ca, cert, key = path / "ca.crt", path / "client.crt", path / "client.key"
    return {"ok": True, "identity": safe, "provisioned": ca.is_file() and cert.is_file() and key.is_file(), "ca_present": ca.is_file(), "client_certificate_present": cert.is_file(), "private_key_present": key.is_file(), "private_key_exported": False}


def workload_identity_x509_provision(identity: str, leaf_days: int = 90, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    try:
        safe = _x509_identity(identity)
        days = int(leaf_days)
        if days < 1 or days > 365:
            return {"ok": False, "error": "leaf_days_out_of_range"}
        target = _x509_dir(safe)
    except (ValueError, PermissionError):
        return {"ok": False, "error": "invalid_x509_identity"}
    root = target.parent
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    if target.exists():
        return {"ok": False, "error": "x509_identity_already_exists", "rotation_required": True}
    tmp = Path(tempfile.mkdtemp(prefix=f".{safe}.", dir=str(root)))
    try:
        commands = [
            ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "ca.key"],
            ["openssl", "req", "-x509", "-new", "-sha256", "-key", "ca.key", "-days", "3650", "-subj", f"/CN=Vitrine Workload CA {safe}", "-out", "ca.crt"],
            ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "client.key"],
            ["openssl", "req", "-new", "-sha256", "-key", "client.key", "-subj", f"/CN={safe}", "-out", "client.csr"],
        ]
        for command in commands:
            proc = subprocess.run(command, cwd=str(tmp), text=True, capture_output=True, timeout=60, check=False)
            if proc.returncode != 0:
                return {"ok": False, "error": "openssl_generation_failed"}
        (tmp / "client.ext").write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n" + f"subjectAltName=URI:spiffe://vitrineiapro/workload/{safe}\n", encoding="utf-8")
        signed = subprocess.run(["openssl", "x509", "-req", "-in", "client.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", "client.crt", "-days", str(days), "-sha256", "-extfile", "client.ext"], cwd=str(tmp), text=True, capture_output=True, timeout=60, check=False)
        if signed.returncode != 0:
            return {"ok": False, "error": "openssl_sign_failed"}
        os.chmod(tmp / "ca.key", 0o600); os.chmod(tmp / "client.key", 0o600)
        os.chmod(tmp / "ca.crt", 0o644); os.chmod(tmp / "client.crt", 0o644); os.chmod(tmp, 0o700)
        os.replace(tmp, target)
        return {"ok": True, "status": "provisioned", "identity": safe, "leaf_days": days, "ca_pem": (target / "ca.crt").read_text(encoding="utf-8"), "private_key_present": True, "private_key_exported": False}
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def connector_health() -> dict[str, Any]:
    projects = []
    if PROJECT_MANIFEST_ROOT.is_dir():
        projects = sorted(path.stem for path in PROJECT_MANIFEST_ROOT.glob("*.json") if path.is_file())
    return {
        "ok": True,
        "connector_id": CONNECTOR_ID,
        "display_name": CONNECTOR_DISPLAY_NAME,
        "version": CONNECTOR_VERSION,
        "registry": "single-fastmcp-main",
        "manifest_root": str(PROJECT_MANIFEST_ROOT),
        "projects": projects,
        "capabilities": [
            "connector_health",
            "project_context",
            "project_status",
            "project_deploy",
            "project_write_file",
            "project_php_lint",
            "tvsumare_operations",
        ],
    }

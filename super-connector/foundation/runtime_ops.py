from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import main


def _safe_runtime_key(value: str) -> str:
    key = str(value or "").strip()
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if not key or len(key) > 128 or key[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" or any(ch not in allowed for ch in key):
        raise ValueError("invalid_runtime_key")
    return key


def _safe_runtime_keys(values: list[str]) -> list[str]:
    keys: list[str] = []
    for raw in values or []:
        key = _safe_runtime_key(raw)
        if key not in keys:
            keys.append(key)
    return keys


def _workspace(project: dict[str, Any]) -> Path:
    workspace = Path(project["workspace"]["root"]).resolve()
    if not any(workspace == root or root in workspace.parents for root in main.WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    return workspace


def _runtime_path(project: dict[str, Any]) -> Path:
    workspace = _workspace(project)
    raw = str(project.get("runtime", {}).get("env_file", ".env.runtime") or ".env.runtime").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        raise ValueError("invalid_runtime_env_file")
    path = (workspace / raw).resolve()
    if workspace != path.parent and workspace not in path.parents:
        raise PermissionError("runtime_env_outside_workspace")
    return path


def _parse_present_keys(path: Path) -> set[str]:
    present: set[str] = set()
    if not path.is_file():
        return present
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        try:
            present.add(_safe_runtime_key(key))
        except ValueError:
            continue
    return present


def _read_secret(project: dict[str, Any], key: str) -> str:
    path = _runtime_path(project)
    if not path.is_file():
        raise FileNotFoundError("runtime_env_missing")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            secret = value.strip()
            if not secret:
                raise ValueError("runtime_secret_empty")
            return secret
    raise KeyError("runtime_secret_missing")


def runtime_config_status(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    path = _runtime_path(project)
    allowed = _safe_runtime_keys(list(project.get("runtime", {}).get("allowed_keys", []) or []))
    present = _parse_present_keys(path)
    result = {
        "ok": True,
        "project_id": project_id,
        "env_file": str(project.get("runtime", {}).get("env_file", ".env.runtime")),
        "allowed_keys": allowed,
        "secrets": {key: {"present": key in present} for key in allowed},
        "file_exists": path.is_file(),
    }
    main._audit("runtime.config_status", {"project_id": project_id}, {"ok": True, "allowed_key_count": len(allowed), "file_exists": path.is_file()})
    return result


def manifest_runtime_configure(project_id: str, runtime_allowed_keys: list[str], runtime_env_file: str = ".env.runtime", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project = main._load_project(project_id)
    workspace = _workspace(project)
    raw = str(runtime_env_file or ".env.runtime").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        return {"ok": False, "error": "invalid_runtime_env_file"}
    target = (workspace / raw).resolve()
    if workspace != target.parent and workspace not in target.parents:
        return {"ok": False, "error": "runtime_env_outside_workspace"}
    try:
        allowed = _safe_runtime_keys(runtime_allowed_keys)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    project["runtime"] = {"env_file": raw, "allowed_keys": allowed}
    registry = main._registry_path(project_id)
    registry.parent.mkdir(parents=True, exist_ok=True)
    tmp = registry.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, registry)
    result = {"ok": True, "project_id": project_id, "env_file": raw, "allowed_keys": allowed}
    main._audit("runtime.manifest_configure", {"project_id": project_id, "env_file": raw, "allowed_keys": allowed}, result)
    return result


def runtime_secret_set(project_id: str, key: str, value: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project = main._load_project(project_id)
    try:
        safe_key = _safe_runtime_key(key)
        allowed = _safe_runtime_keys(list(project.get("runtime", {}).get("allowed_keys", []) or []))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if safe_key not in allowed:
        return {"ok": False, "error": "runtime_key_not_allowed", "key": safe_key}
    secret = str(value or "")
    if not secret or len(secret) > 16384 or any(ch in secret for ch in "\r\n\x00"):
        return {"ok": False, "error": "invalid_secret_value"}
    path = _runtime_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    replacement = f"{safe_key}={secret}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#") and "=" in stripped and stripped.split("=", 1)[0].strip() == safe_key:
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)
    payload = "\n".join(updated).rstrip("\n") + "\n"
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    result = {"ok": True, "project_id": project_id, "key": safe_key, "stored": True, "env_file": str(project.get("runtime", {}).get("env_file", ".env.runtime"))}
    main._audit("runtime.secret_set", {"project_id": project_id, "key": safe_key}, {"ok": True, "stored": True})
    return result


def gemini_api_probe(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    allowed = _safe_runtime_keys(list(project.get("runtime", {}).get("allowed_keys", []) or []))
    if "GEMINI_API_KEY" not in allowed:
        return {"ok": False, "error": "gemini_api_key_not_allowed"}
    try:
        secret = _read_secret(project, "GEMINI_API_KEY")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
        headers={"x-goog-api-key": secret, "Accept": "application/json", "User-Agent": "vitrine-super/0.2"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = int(response.status)
            payload = json.loads(response.read(1000000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        result = {"ok": False, "http_status": int(exc.code), "error": "gemini_http_error", "detail": body[:1000]}
        main._audit("runtime.gemini_probe", {"project_id": project_id}, {"ok": False, "http_status": int(exc.code)})
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        result = {"ok": False, "error": "gemini_probe_failed", "detail": type(exc).__name__}
        main._audit("runtime.gemini_probe", {"project_id": project_id}, result)
        return result
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = [str(item.get("name", "")) for item in models if isinstance(item, dict) and item.get("name")]
    veo_models = [name for name in names if "veo" in name.lower()]
    result = {
        "ok": status == 200,
        "http_status": status,
        "authenticated": status == 200,
        "model_count": len(names),
        "veo_models": veo_models[:20],
        "gemini_models_sample": [name for name in names if "gemini" in name.lower()][:20],
    }
    main._audit("runtime.gemini_probe", {"project_id": project_id}, {"ok": result["ok"], "http_status": status, "model_count": len(names), "veo_count": len(veo_models)})
    return result

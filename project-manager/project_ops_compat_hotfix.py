from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
FILES = {
    "main": ROOT / "main.py",
    "tools": ROOT / "project_manager_tools.py",
    "operations": ROOT / "project_manager_operations.py",
}


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"required_file_missing:{path.name}")


def backup(path: Path) -> Path:
    target = path.with_name(f"{path.name}.backup-project-ops-hotfix-{STAMP}")
    shutil.copy2(path, target)
    return target


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"marker_missing:{label}")
    return text.replace(old, new, 1)


def insert_before(text: str, marker: str, block: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_missing:{label}")
    return text.replace(marker, block + marker, 1)


def patch_tools(text: str) -> str:
    text = text.replace('"/projects/container/exec",', '"/projects/docker/container-exec",')

    compatibility = '''\n\ndef project_http_check(project_id: str, url: str, method: str = "GET") -> dict[str, Any]:\n    return _request(\n        "POST",\n        "/projects/http-check",\n        {"project_id": project_id, "url": url, "method": method},\n    )\n\n\ndef project_port_check(project_id: str, host: str, port: int) -> dict[str, Any]:\n    return _request(\n        "POST",\n        "/projects/port-check",\n        {"project_id": project_id, "host": host, "port": port},\n    )\n\n\ndef connector_patch(\n    path: str,\n    old_text: str,\n    new_text: str,\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _request(\n        "POST",\n        "/connector/patch",\n        {"path": path, "old_text": old_text, "new_text": new_text, "confirm": confirm},\n    )\n'''
    return insert_before(
        text,
        "\ndef project_workspace_action(\n",
        compatibility,
        "def connector_patch(",
        "project_manager_tools_compatibility",
    )


def patch_operations(text: str) -> str:
    text = replace_once(
        text,
        "import re\nimport subprocess\n",
        "import re\nimport socket\nimport subprocess\nimport urllib.error\nimport urllib.request\n",
        "operations_imports",
    )

    text = replace_once(
        text,
        'SAFE_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")\n',
        'SAFE_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")\n'
        'SAFE_HOST_RE = re.compile(r"^(127\\.0\\.0\\.1|localhost|[A-Za-z0-9.-]+)$")\n'
        'SAFE_EXEC_BINARIES = {"php", "node", "npm", "composer", "cat", "ls", "find", "grep", "test"}\n'
        'SAFE_ARTISAN_COMMANDS = {\n'
        '    "about", "optimize:clear", "config:clear", "cache:clear", "route:clear", "view:clear",\n'
        '    "filament:assets", "route:list", "migrate:status",\n'
        '}\n',
        "operations_safety_constants",
    )

    models = '''\n\nclass ProjectContainerExecRequest(ProjectContainerRequest):\n    command: list[str]\n    workdir: str = "/var/www/html"\n    confirm: str = ""\n\n\nclass ProjectHttpRequest(BaseModel):\n    project_id: str\n    url: str\n    method: str = "GET"\n\n\nclass ProjectPortRequest(BaseModel):\n    project_id: str\n    host: str\n    port: int\n'''
    text = insert_before(
        text,
        "\n\nclass ProjectComposeRmRequest(BaseModel):\n",
        models,
        "class ProjectContainerExecRequest(",
        "operations_request_models",
    )

    validator = '''\n\ndef validate_exec(command: list[str]) -> tuple[list[str], bool]:\n    if not command or len(command) > 20 or any(len(part) > 500 for part in command):\n        raise HTTPException(status_code=422, detail="invalid_command")\n    binary = command[0]\n    if binary not in SAFE_EXEC_BINARIES:\n        raise HTTPException(status_code=403, detail="command_not_allowed")\n    mutating = False\n    if binary == "php" and len(command) >= 3 and command[1] == "artisan":\n        artisan = command[2]\n        if artisan not in SAFE_ARTISAN_COMMANDS:\n            raise HTTPException(status_code=403, detail="artisan_command_not_allowed")\n        mutating = artisan in {\n            "optimize:clear", "config:clear", "cache:clear", "route:clear", "view:clear", "filament:assets"\n        }\n    elif binary in {"npm", "composer"}:\n        allowed = {\n            ("npm", "run", "build"),\n            ("npm", "test"),\n            ("npm", "run", "test"),\n            ("composer", "validate"),\n            ("composer", "install"),\n        }\n        if not any(tuple(command[:len(item)]) == item for item in allowed):\n            raise HTTPException(status_code=403, detail="package_command_not_allowed")\n        mutating = binary == "composer" and len(command) > 1 and command[1] == "install"\n    return command, mutating\n'''
    text = insert_before(
        text,
        "\n\ndef redact_container_env(env_items: list[str]) -> dict[str, str]:\n",
        validator,
        "def validate_exec(command:",
        "operations_exec_validator",
    )

    routes = '''\n\n@router.post("/docker/container-exec", dependencies=[Depends(auth)])\ndef project_container_exec(req: ProjectContainerExecRequest) -> dict[str, Any]:\n    manifest = load_manifest(req.project_id)\n    root, _, _ = project_paths(manifest)\n    name = validate_container_name(req.container_name)\n    command, mutating = validate_exec(req.command)\n    if not req.workdir.startswith("/") or ".." in Path(req.workdir).parts:\n        raise HTTPException(status_code=422, detail="invalid_workdir")\n    if mutating and req.confirm != "EXECUTAR":\n        raise HTTPException(status_code=409, detail="confirmation_required:EXECUTAR")\n    result = run(["docker", "exec", "-w", req.workdir, name, *command], root)\n    audit(\n        "project_container_exec",\n        req.project_id,\n        {"project_id": req.project_id, "container_name": name, "command": command, "workdir": req.workdir},\n        result,\n    )\n    return result\n\n\n@router.post("/http-check", dependencies=[Depends(auth)])\ndef project_http_check(req: ProjectHttpRequest) -> dict[str, Any]:\n    load_manifest(req.project_id)\n    if not req.url.startswith(("http://", "https://")):\n        raise HTTPException(status_code=422, detail="invalid_url")\n    method = req.method.upper()\n    if method not in {"GET", "HEAD"}:\n        raise HTTPException(status_code=422, detail="invalid_method")\n    request = urllib.request.Request(req.url, method=method, headers={"User-Agent": "Vitrine-Ops/1.0"})\n    try:\n        with urllib.request.urlopen(request, timeout=20) as response:\n            result = {\n                "ok": True,\n                "status": response.status,\n                "final_url": response.geturl(),\n                "headers": dict(response.headers.items()),\n            }\n    except urllib.error.HTTPError as exc:\n        result = {\n            "ok": False,\n            "status": exc.code,\n            "final_url": exc.geturl(),\n            "headers": dict(exc.headers.items()),\n        }\n    except Exception as exc:\n        result = {"ok": False, "error": type(exc).__name__}\n    audit("project_http_check", req.project_id, req.model_dump(), result)\n    return result\n\n\n@router.post("/port-check", dependencies=[Depends(auth)])\ndef project_port_check(req: ProjectPortRequest) -> dict[str, Any]:\n    load_manifest(req.project_id)\n    if not SAFE_HOST_RE.fullmatch(req.host) or not 1 <= req.port <= 65535:\n        raise HTTPException(status_code=422, detail="invalid_host_or_port")\n    try:\n        with socket.create_connection((req.host, req.port), timeout=5):\n            result = {"ok": True, "host": req.host, "port": req.port, "open": True}\n    except OSError as exc:\n        result = {"ok": True, "host": req.host, "port": req.port, "open": False, "error": type(exc).__name__}\n    audit("project_port_check", req.project_id, req.model_dump(), result)\n    return result\n'''
    return insert_before(
        text,
        "\n\n@router.post(\"/php-lint\", dependencies=[Depends(auth)])\n",
        routes,
        'def project_http_check(req:',
        "operations_compat_routes",
    )


def patch_main(text: str) -> str:
    import_start = text.find("from project_manager_tools import (")
    if import_start < 0:
        raise RuntimeError("marker_missing:main_project_manager_import")
    import_end = text.find(")\n", import_start)
    if import_end < 0:
        raise RuntimeError("marker_missing:main_project_manager_import_end")

    additions = (
        "    project_http_check as _project_http_check,\n",
        "    project_port_check as _project_port_check,\n",
        "    project_container_exec as _project_container_exec,\n",
        "    connector_patch as _connector_patch,\n",
    )
    for line in additions:
        block = text[import_start:import_end]
        if line.strip() not in block:
            text = text[:import_end] + line + text[import_end:]
            import_end += len(line)

    patch_tool = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef connector_patch(\n    path: str,\n    old_text: str,\n    new_text: str,\n    confirm: str = "",\n) -> dict[str, Any]:\n    """Aplica patch controlado somente na allowlist oficial do conector."""\n    return _connector_patch(path, old_text, new_text, confirm)\n'''
    text = insert_before(
        text,
        '\nif __name__ == "__main__":\n',
        patch_tool,
        "def connector_patch(\n",
        "main_connector_patch_tool",
    )
    return text


def validate() -> None:
    for path in FILES.values():
        py_compile.compile(str(path), doraise=True)

    tests = ROOT / "tests"
    if tests.is_dir():
        proc = subprocess.run(
            [
                os.sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_connector_tools.py",
                "-v",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError("connector_tests_failed:" + proc.stderr[-2000:])


def main() -> int:
    for path in FILES.values():
        require_file(path)

    backups = {name: backup(path) for name, path in FILES.items()}
    try:
        FILES["tools"].write_text(patch_tools(FILES["tools"].read_text(encoding="utf-8")), encoding="utf-8")
        FILES["operations"].write_text(
            patch_operations(FILES["operations"].read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        FILES["main"].write_text(patch_main(FILES["main"].read_text(encoding="utf-8")), encoding="utf-8")
        validate()
    except Exception:
        for name, backup_path in backups.items():
            shutil.copy2(backup_path, FILES[name])
        raise

    print(json.dumps({"ok": True, "patched": [str(path) for path in FILES.values()], "backups": {k: str(v) for k, v in backups.items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

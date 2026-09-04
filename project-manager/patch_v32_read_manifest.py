from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-v32-{STAMP}'))


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise RuntimeError(f'{label}: marcador nao encontrado')


def patch_file_operations() -> None:
    path = ROOT / 'project_file_operations.py'
    backup(path)
    text = path.read_text(encoding='utf-8')

    # Build49/Python: liberar somente raizes de codigo declaradas.
    require(text, 'ALLOWED_PROJECT_ROOTS = {', 'ALLOWED_PROJECT_ROOTS')
    if '    "agentes",\n' not in text:
        text = text.replace('ALLOWED_PROJECT_ROOTS = {\n', 'ALLOWED_PROJECT_ROOTS = {\n    "agentes",\n', 1)
    if '    "core",\n' not in text:
        text = text.replace('ALLOWED_PROJECT_ROOTS = {\n', 'ALLOWED_PROJECT_ROOTS = {\n    "core",\n', 1)

    require(text, 'TEXT_SUFFIXES = {', 'TEXT_SUFFIXES')
    if '".py"' not in text:
        text = text.replace(
            '    ".js", ".ts", ".css", ".scss", ".vue", ".sql", ".sh",\n',
            '    ".js", ".ts", ".css", ".scss", ".vue", ".sql", ".sh", ".py",\n',
            1,
        )

    if 'def read_project_file(' not in text:
        marker = '\ndef write_project_file(\n'
        require(text, marker, 'read_project_file insertion')
        block = '''\n\ndef read_project_file(\n    repository: Path,\n    path: str,\n    *,\n    start_line: int = 1,\n    end_line: int = 400,\n) -> dict[str, Any]:\n    relative, target = safe_project_file(repository, path, must_exist=True)\n    if start_line < 1 or end_line < start_line or end_line - start_line > 2000:\n        _fail(422, "invalid_line_range")\n    try:\n        lines = target.read_text(encoding="utf-8").splitlines()\n    except UnicodeDecodeError:\n        _fail(403, "non_text_path_blocked")\n    selected = lines[start_line - 1:end_line]\n    return {\n        "ok": True,\n        "path": relative,\n        "start_line": start_line,\n        "end_line": min(end_line, len(lines)),\n        "total_lines": len(lines),\n        "content": "\\n".join(selected),\n    }\n'''
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def patch_manager_operations() -> None:
    path = ROOT / 'project_manager_operations.py'
    backup(path)
    text = path.read_text(encoding='utf-8')

    # Importar leitura segura.
    import_anchor = '    php_lint_project_file,\n'
    require(text, import_anchor, 'project_file_operations import')
    if '    read_project_file,\n' not in text:
        text = text.replace(import_anchor, import_anchor + '    read_project_file,\n', 1)

    # Modelos de request usados pelas novas rotas.
    if 'class ProjectReadRequest(BaseModel):' not in text:
        marker = '\n\nclass ProjectPathRequest(BaseModel):\n    project_id: str\n    path: str\n'
        require(text, marker, 'ProjectPathRequest')
        block = marker + '''\n\nclass ProjectReadRequest(BaseModel):\n    project_id: str\n    path: str\n    start_line: int = 1\n    end_line: int = 400\n\n\nclass ProjectManifestCreateRequest(BaseModel):\n    project_id: str\n    name: str\n    workspace_root: str\n    repository_url: str\n    branch: str = "main"\n    repository_directory: str = "repository"\n    shared_directories: list[str] = []\n    compose_file: str = ""\n    docker_project: str = ""\n    release_directory: str = "releases"\n    confirm: str = ""\n'''
        text = text.replace(marker, block, 1)

    # Criacao declarativa de manifest. Mantem confinamento de workspace.
    if 'def project_manifest_create(' not in text:
        marker = '\n\n@router.get("/{project_id}/manifest", dependencies=[Depends(auth)])\n'
        require(text, marker, 'manifest route insertion')
        block = '''\n\n@router.post("/manifest/create", dependencies=[Depends(auth)])\ndef project_manifest_create(req: ProjectManifestCreateRequest) -> dict[str, Any]:\n    if req.confirm != "EXECUTAR":\n        raise HTTPException(status_code=422, detail="confirmation_required")\n    project_id = req.project_id.strip()\n    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):\n        raise HTTPException(status_code=422, detail="invalid_project_id")\n    root = validated_workspace_root(req.workspace_root)\n    repository_directory = req.repository_directory.strip() or "repository"\n    release_directory = req.release_directory.strip() or "releases"\n    validated_child(root, repository_directory, "repository_directory")\n    validated_child(root, release_directory, "release_directory")\n    shared = [str(item).strip() for item in req.shared_directories if str(item).strip()]\n    for item in shared:\n        validated_child(root / "shared", item, "shared_directory")\n    manifest = {\n        "id": project_id,\n        "name": req.name.strip() or project_id,\n        "workspace_root": str(root),\n        "repository": {\n            "url": req.repository_url.strip(),\n            "branch": req.branch.strip() or "main",\n            "directory": repository_directory,\n        },\n        "shared_directories": shared,\n        "docker": {\n            "compose_file": req.compose_file.strip(),\n            "project_name": req.docker_project.strip() or project_id,\n        },\n        "domains": {"homologation": [], "production": []},\n        "release": {"directory": release_directory, "exclude": [".git", ".env", "shared", "data", "uploads", "logs", "vendor", "node_modules"]},\n    }\n    if not manifest["repository"]["url"]:\n        raise HTTPException(status_code=422, detail="repository_url_missing")\n    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)\n    target = (MANIFEST_ROOT / f"{project_id}.json").resolve()\n    if not is_within(target, MANIFEST_ROOT):\n        raise HTTPException(status_code=403, detail="manifest_path_blocked")\n    if target.exists():\n        raise HTTPException(status_code=409, detail="manifest_already_exists")\n    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")\n    result = {"ok": True, "project_id": project_id, "manifest": manifest}\n    audit("project_manifest_create", project_id, {"project_id": project_id}, result)\n    return result\n'''
        text = text.replace(marker, block + marker, 1)

    if 'def project_read_file(' not in text:
        marker = '\n\n@router.post("/write-file", dependencies=[Depends(auth)])\n'
        require(text, marker, 'read route insertion')
        block = '''\n\n@router.post("/read-file", dependencies=[Depends(auth)])\ndef project_read_file(req: ProjectReadRequest) -> dict[str, Any]:\n    try:\n        manifest = load_manifest(req.project_id)\n        _, repository, _ = project_paths(manifest)\n        result = read_project_file(\n            repository,\n            req.path,\n            start_line=req.start_line,\n            end_line=req.end_line,\n        )\n        result["project_id"] = req.project_id\n        audit("project_read_file", req.project_id, {"path": result["path"], "start_line": req.start_line, "end_line": req.end_line}, {"ok": True, "path": result["path"]})\n        return result\n    except ProjectFileOperationError as exc:\n        http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)\n        _safe_audit_failure("project_read_file", req.project_id, req.path, http_exc)\n        raise http_exc from exc\n    except HTTPException as exc:\n        _safe_audit_failure("project_read_file", req.project_id, req.path, exc)\n        raise\n'''
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def patch_tools() -> None:
    path = ROOT / 'project_manager_tools.py'
    backup(path)
    text = path.read_text(encoding='utf-8')

    if 'def project_read_file(' not in text:
        marker = '\n\ndef project_write_file(\n'
        require(text, marker, 'tools read insertion')
        block = '''\n\ndef project_read_file(\n    project_id: str,\n    path: str,\n    start_line: int = 1,\n    end_line: int = 400,\n) -> dict[str, Any]:\n    return _request(\n        "POST",\n        "/projects/read-file",\n        {"project_id": project_id, "path": path, "start_line": start_line, "end_line": end_line},\n    )\n'''
        text = text.replace(marker, block + marker, 1)

    if 'def project_manifest_create(' not in text:
        marker = '\n\ndef project_manifest(project_id: str) -> dict[str, Any]:\n'
        require(text, marker, 'tools manifest insertion')
        block = '''\n\ndef project_manifest_create(\n    project_id: str,\n    name: str,\n    workspace_root: str,\n    repository_url: str,\n    branch: str = "main",\n    repository_directory: str = "repository",\n    shared_directories: list[str] | None = None,\n    compose_file: str = "",\n    docker_project: str = "",\n    release_directory: str = "releases",\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _request(\n        "POST",\n        "/projects/manifest/create",\n        {\n            "project_id": project_id,\n            "name": name,\n            "workspace_root": workspace_root,\n            "repository_url": repository_url,\n            "branch": branch,\n            "repository_directory": repository_directory,\n            "shared_directories": shared_directories or [],\n            "compose_file": compose_file,\n            "docker_project": docker_project,\n            "release_directory": release_directory,\n            "confirm": confirm,\n        },\n    )\n'''
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def patch_main() -> None:
    path = ROOT / 'main.py'
    backup(path)
    text = path.read_text(encoding='utf-8')

    # Acrescentar imports aos blocos existentes do Project Manager.
    import_start = text.find('from project_manager_tools import (')
    if import_start == -1:
        raise RuntimeError('main.py: bloco project_manager_tools nao encontrado')
    import_end = text.find(')\n', import_start)
    if import_end == -1:
        raise RuntimeError('main.py: fechamento de imports nao encontrado')
    for line in (
        '    project_read_file as _project_read_file,\n',
        '    project_manifest_create as _project_manifest_create,\n',
    ):
        current = text[import_start:import_end]
        if line.strip() not in current:
            text = text[:import_end] + line + text[import_end:]
            import_end += len(line)

    if 'def project_read_file(' not in text:
        marker = '\nif __name__ == "__main__":\n'
        require(text, marker, 'main read tool insertion')
        block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:\n    return _project_read_file(project_id, path, start_line, end_line)\n'''
        text = text.replace(marker, block + marker, 1)

    if 'def project_manifest_create(' not in text:
        marker = '\nif __name__ == "__main__":\n'
        require(text, marker, 'main manifest tool insertion')
        block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_manifest_create(\n    project_id: str,\n    name: str,\n    workspace_root: str,\n    repository_url: str,\n    branch: str = "main",\n    repository_directory: str = "repository",\n    shared_directories: list[str] | None = None,\n    compose_file: str = "",\n    docker_project: str = "",\n    release_directory: str = "releases",\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_manifest_create(project_id, name, workspace_root, repository_url, branch, repository_directory, shared_directories, compose_file, docker_project, release_directory, confirm)\n'''
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f'Conector nao encontrado: {ROOT}')
    for required in ('project_file_operations.py', 'project_manager_operations.py', 'project_manager_tools.py', 'main.py'):
        if not (ROOT / required).is_file():
            raise SystemExit(f'Arquivo obrigatorio ausente: {ROOT / required}')

    patch_file_operations()
    patch_manager_operations()
    patch_tools()
    patch_main()

    print('V32_PROJECT_READ_MANIFEST_PATCHED')
    print(f'BACKUP_STAMP={STAMP}')
    print('NEXT=python -m py_compile project_file_operations.py project_manager_operations.py project_manager_tools.py main.py')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()

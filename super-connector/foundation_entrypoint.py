from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import main
import materialize_entrypoint  # noqa: F401 - registers v0.1.2-compatible tools
from foundation import capabilities, docker_ops, files_ops, git_ops, laravel_ops, php_ops, policy, recovery_ops, runtime_ops

main.VERSION = "0.3.9-safe-file-replace"


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def policy_catalog() -> dict[str, Any]:
    result = {"ok": True, "policies": policy.catalog()}
    main._audit("policy.catalog", {}, {"ok": True, "count": len(result["policies"])})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_register_existing_readonly(project_id: str, workspace_root: str, name: str = "", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    try:
        safe_id = main._safe_project_id(project_id)
        workspace = main.Path(str(workspace_root or "").strip()).resolve()
        if not any(workspace == root or root in workspace.parents for root in main.WORKSPACE_ROOTS):
            raise PermissionError("workspace_root_blocked")
        if not workspace.is_dir():
            result = {"ok": False, "error": "workspace_not_found", "workspace_root": str(workspace)}
            main._audit("project.register_existing_readonly", {"project_id": project_id, "workspace_root": workspace_root}, result)
            return result
        target = main._registry_path(safe_id)
        if target.exists():
            result = {"ok": False, "error": "project_already_registered", "project_id": safe_id}
            main._audit("project.register_existing_readonly", {"project_id": project_id, "workspace_root": workspace_root}, result)
            return result
        project = {
            "id": safe_id,
            "name": str(name or safe_id),
            "repository": {"url": "", "branch": "", "directory": "."},
            "workspace": {"root": str(workspace)},
            "docker": {"compose_file": "", "project_name": safe_id},
            "runtime": {"env_file": ".env.runtime", "allowed_keys": []},
            "policies": {
                "dirty_tree": "preserve",
                "allow_reset": False,
                "allow_clean": False,
                "backup_before_mutation": False,
                "read_only_workspace": True,
            },
        }
        main.REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(main.json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        main.os.replace(tmp, target)
        result = {"ok": True, "status": "registered_readonly", "project_id": safe_id, "workspace_root": str(workspace)}
    except (ValueError, PermissionError, OSError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("project.register_existing_readonly", {"project_id": project_id, "workspace_root": workspace_root}, result)
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_bootstrap_from_git(
    project_id: str,
    name: str,
    workspace_root: str,
    repository_url: str,
    branch: str = "main",
    repository_directory: str = "repository",
    runtime_env_file: str = ".env.runtime",
    runtime_allowed_keys: list[str] | None = None,
    confirm: str = "",
) -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}

    try:
        safe_id = main._safe_project_id(project_id)
        safe_branch = main._safe_branch(branch)
        safe_url = materialize_entrypoint._safe_repository_url(repository_url)
        workspace = Path(str(workspace_root or "").strip()).resolve()
        if not any(workspace == root or root in workspace.parents for root in main.WORKSPACE_ROOTS):
            raise PermissionError("workspace_root_blocked")

        repo_dir = str(repository_directory or "repository").strip().replace("\\", "/")
        if not repo_dir or repo_dir.startswith("/") or ".." in repo_dir.split("/"):
            raise ValueError("invalid_repository_directory")

        runtime_file = str(runtime_env_file or ".env.runtime").strip().replace("\\", "/")
        if not runtime_file or runtime_file.startswith("/") or ".." in runtime_file.split("/"):
            raise ValueError("invalid_runtime_env_file")

        allowed_keys: list[str] = []
        for raw in runtime_allowed_keys or []:
            key = str(raw or "").strip()
            if not key or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in key):
                raise ValueError(f"invalid_runtime_key:{key}")
            if key not in allowed_keys:
                allowed_keys.append(key)

        target = main._registry_path(safe_id)
        requested = {
            "id": safe_id,
            "name": str(name or safe_id),
            "repository": {"url": safe_url, "branch": safe_branch, "directory": repo_dir},
            "workspace": {"root": str(workspace)},
            "docker": {"compose_file": "", "project_name": safe_id},
            "runtime": {"env_file": runtime_file, "allowed_keys": allowed_keys},
            "policies": {
                "dirty_tree": "preserve",
                "allow_reset": False,
                "allow_clean": False,
                "backup_before_mutation": False,
            },
        }

        if target.exists():
            existing = main.json.loads(target.read_text(encoding="utf-8"))
            identity = (
                existing.get("id") == requested["id"]
                and existing.get("repository", {}).get("url") == safe_url
                and existing.get("repository", {}).get("branch") == safe_branch
                and existing.get("repository", {}).get("directory") == repo_dir
                and existing.get("workspace", {}).get("root") == str(workspace)
            )
            if not identity:
                result = {"ok": False, "error": "project_already_registered_with_different_identity", "project_id": safe_id}
                main._audit("project.bootstrap_from_git", {"project_id": safe_id}, result)
                return result
        else:
            main.REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(main.json.dumps(requested, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            main.os.replace(tmp, target)

        repository = (workspace / repo_dir).resolve()
        if workspace != repository and workspace not in repository.parents:
            raise PermissionError("repository_outside_workspace")

        if (repository / ".git").is_dir():
            head_branch = main._run(["git", "branch", "--show-current"], repository, timeout=30)
            current_branch = str(head_branch.get("stdout", "")).strip() if head_branch.get("ok") else ""
            if current_branch and current_branch != safe_branch:
                result = {"ok": False, "error": "repository_branch_mismatch", "project_id": safe_id, "expected_branch": safe_branch, "current_branch": current_branch}
                main._audit("project.bootstrap_from_git", {"project_id": safe_id}, result)
                return result
            result = {"ok": True, "status": "already_materialized", "project_id": safe_id, "workspace": str(workspace), "repository": str(repository), "branch": safe_branch}
            main._audit("project.bootstrap_from_git", {"project_id": safe_id}, result)
            return result

        materialized = materialize_entrypoint.project_materialize(safe_id, confirm="EXECUTAR")
        result = {
            **materialized,
            "status": "bootstrapped" if materialized.get("ok") else "registered_materialize_failed",
            "registry_created": True,
        }
        main._audit("project.bootstrap_from_git", {"project_id": safe_id, "branch": safe_branch, "workspace": str(workspace)}, {"ok": result.get("ok"), "status": result.get("status")})
        return result
    except (ValueError, PermissionError, OSError, main.json.JSONDecodeError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
        main._audit("project.bootstrap_from_git", {"project_id": project_id}, result)
        return result


_BACKUP_ARCHIVE_ROOT = Path("/backup-archives")
_BACKUP_AUDIT_ROOT = Path("/srv/projects/conheca-sumare-recovery-4x-audit")
_BACKUP_ARCHIVE_MAP = {
    "Guia-Digital-da-Cidade-Visite-Sumare-4.1-TESTE.zip": "4.1-teste",
    "Guia-Digital-da-Cidade-Visite-Sumare-4.1-RC1-Atualizada.zip": "4.1-rc1",
    "Guia-Digital-da-Cidade-Visite-Sumare-4.3-FONTES-OFICIAIS.zip": "4.3-fontes-oficiais",
    "reuniao_ia_pwa_mobile_build_1_0.zip": "ia-pwa-mobile",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def backup_archive_materialize(archive_name: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    archive_name = str(archive_name or "").strip()
    destination_name = _BACKUP_ARCHIVE_MAP.get(archive_name)
    if not destination_name:
        return {"ok": False, "error": "archive_not_allowed", "archive_name": archive_name}
    source = (_BACKUP_ARCHIVE_ROOT / archive_name).resolve()
    root = _BACKUP_ARCHIVE_ROOT.resolve()
    try:
        source.relative_to(root)
    except ValueError:
        return {"ok": False, "error": "archive_path_blocked", "archive_name": archive_name}
    if not source.is_file() or source.is_symlink():
        return {"ok": False, "error": "archive_not_found", "archive_name": archive_name}
    package_root = (_BACKUP_AUDIT_ROOT / destination_name).resolve()
    if package_root.exists() and any(package_root.iterdir()):
        return {"ok": False, "error": "destination_not_empty", "destination": str(package_root)}
    package_root.mkdir(parents=True, exist_ok=True)
    copied_archive = package_root / "source.zip"
    extracted_root = package_root / "extracted"
    source_sha256 = _sha256_file(source)
    shutil.copy2(source, copied_archive)
    if _sha256_file(copied_archive) != source_sha256:
        return {"ok": False, "error": "archive_hash_mismatch", "archive_name": archive_name}
    try:
        with zipfile.ZipFile(copied_archive, "r") as archive:
            members = archive.infolist()
            if len(members) > 10000:
                raise ValueError("archive_entry_limit_exceeded")
            if sum(max(0, int(member.file_size)) for member in members) > 2 * 1024 * 1024 * 1024:
                raise ValueError("archive_uncompressed_size_limit_exceeded")
            for member in members:
                member_path = PurePosixPath(member.filename.replace("\\", "/"))
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError("zip_slip_blocked")
                if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("zip_symlink_blocked")
            extracted_root.mkdir(parents=True, exist_ok=True)
            archive.extractall(extracted_root)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc), "archive_name": archive_name, "destination": str(package_root)}
        main._audit("backup.archive_materialize", {"archive_name": archive_name}, result)
        return result
    result = {"ok": True, "status": "materialized", "archive_name": archive_name, "destination": str(package_root), "extracted_root": str(extracted_root), "sha256": source_sha256, "source_preserved": True}
    main._audit("backup.archive_materialize", {"archive_name": archive_name}, result)
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_discover(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.discover(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("project.discover", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_capability_check(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.capability_check(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("project.capability_check", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def capability_gap_report(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.gap_report(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("capability.gap_report", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    return files_ops.read_safe(project_id, path, max_bytes)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    return files_ops.read_lines(project_id, path, start_line, end_line)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_file_replace_safe(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]:
    return files_ops.replace_exact(project_id, path, old, new, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_list_files(project_id: str, path: str = ".", max_depth: int = 2, max_entries: int = 1000) -> dict[str, Any]:
    max_depth = max(0, min(int(max_depth), 8))
    max_entries = max(1, min(int(max_entries), 5000))
    try:
        project = main._load_project(project_id)
        repository = main._repository(project).resolve()
        relative = Path(str(path or ".").strip())
        if relative.is_absolute() or ".." in relative.parts:
            raise PermissionError("path_outside_repository")
        root = (repository / relative).resolve()
        root.relative_to(repository)
        if not root.is_dir():
            return {"ok": False, "error": "directory_not_found", "project_id": project_id, "path": path}
        entries: list[dict[str, Any]] = []
        base_depth = len(root.parts)
        stack = [root]
        while stack and len(entries) < max_entries:
            current = stack.pop()
            try:
                children = sorted(current.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            directories: list[Path] = []
            for item in children:
                if len(entries) >= max_entries:
                    break
                try:
                    rel = item.relative_to(repository)
                    is_symlink = item.is_symlink()
                    if is_symlink:
                        item_type = "symlink"
                        size = None
                    elif item.is_dir():
                        item_type = "directory"
                        size = None
                        if len(item.parts) - base_depth < max_depth:
                            directories.append(item)
                    elif item.is_file():
                        item_type = "file"
                        size = item.stat().st_size
                    else:
                        item_type = "other"
                        size = None
                    entries.append({"path": rel.as_posix(), "type": item_type, "size": size})
                except OSError:
                    continue
            stack.extend(reversed(directories))
        result = {
            "ok": True,
            "project_id": project_id,
            "repository": str(repository),
            "path": root.relative_to(repository).as_posix() if root != repository else ".",
            "max_depth": max_depth,
            "entries": entries,
            "truncated": len(entries) >= max_entries,
        }
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id, "path": path}
    main._audit("files.list", {"project_id": project_id, "path": path, "max_depth": max_depth, "max_entries": max_entries}, {"ok": result.get("ok"), "count": len(result.get("entries", []))})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_php_lint(project_id: str, path: str) -> dict[str, Any]:
    return php_ops.php_lint(project_id, path)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_head(project_id: str) -> dict[str, Any]:
    result = git_ops.head(project_id)
    main._audit("git.head", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_log(project_id: str, limit: int = 20) -> dict[str, Any]:
    result = git_ops.log(project_id, limit)
    main._audit("git.log", {"project_id": project_id, "limit": limit}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_diff(project_id: str, ref: str = "HEAD") -> dict[str, Any]:
    result = git_ops.diff(project_id, ref)
    main._audit("git.diff", {"project_id": project_id, "ref": ref}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_reconcile(project_id: str, branch: str = "", confirm: str = "") -> dict[str, Any]:
    return git_ops.reconcile(project_id, branch, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_runtime_config_status(project_id: str) -> dict[str, Any]:
    return runtime_ops.runtime_config_status(project_id)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_manifest_runtime_configure(project_id: str, runtime_allowed_keys: list[str], runtime_env_file: str = ".env.runtime", confirm: str = "") -> dict[str, Any]:
    return runtime_ops.manifest_runtime_configure(project_id, runtime_allowed_keys, runtime_env_file, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_runtime_secret_set(project_id: str, key: str, value: str, confirm: str = "") -> dict[str, Any]:
    return runtime_ops.runtime_secret_set(project_id, key, value, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_runtime_secret_import_from_file(project_id: str, source_path: str, key: str, delete_source: bool = True, confirm: str = "") -> dict[str, Any]:
    return runtime_ops.runtime_secret_import_from_file(project_id, source_path, key, delete_source, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_runtime_secret_copy(source_project_id: str, target_project_id: str, key: str, confirm: str = "") -> dict[str, Any]:
    return runtime_ops.runtime_secret_copy(
        source_project_id,
        target_project_id,
        key,
        confirm,
    )


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_gemini_api_probe(project_id: str) -> dict[str, Any]:
    return runtime_ops.gemini_api_probe(project_id)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def laravel_test_v2(project_id: str) -> dict[str, Any]:
    return laravel_ops.laravel_test_v2(project_id)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_laravel_route_list(project_id: str, service: str, path_prefix: str = "") -> dict[str, Any]:
    return laravel_ops.route_list(project_id, service, path_prefix)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_admin_access_status(project_id: str, email: str, service: str) -> dict[str, Any]:
    return laravel_ops.admin_access_status(project_id, email, service)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_admin_access_repair(project_id: str, email: str, service: str, confirm: str = "") -> dict[str, Any]:
    return laravel_ops.admin_access_repair(project_id, email, service, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_admin_access_reset(project_id: str, email: str, new_password: str, service: str, confirm: str = "") -> dict[str, Any]:
    return laravel_ops.admin_access_reset(project_id, email, new_password, service, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_laravel_migrate_paths(project_id: str, service: str, paths: list[str], confirm: str = "") -> dict[str, Any]:
    return laravel_ops.migrate_paths(project_id, service, paths, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_video_producer_validate(project_id: str) -> dict[str, Any]:
    return php_ops.video_producer_validate(project_id)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_video_producer_download(project_id: str, request_id: str, version_id: str, video_url: str, confirm: str = "") -> dict[str, Any]:
    return php_ops.video_producer_download(project_id, request_id, version_id, video_url, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_video_media_permissions_fix(project_id: str, request_id: str, confirm: str = "") -> dict[str, Any]:
    return php_ops.video_media_permissions_fix(project_id, request_id, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_video_producer_generate(project_id: str, request_id: str, title: str, prompt: str, aspect_ratio: str = "9:16", duration: int = 8, resolution: str = "720p", confirm: str = "") -> dict[str, Any]:
    return php_ops.video_producer_generate(project_id, request_id, title, prompt, aspect_ratio, duration, resolution, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_status() -> dict[str, Any]:
    result = docker_ops.docker_status()
    main._audit("docker.status", {}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_image_inspect(image: str) -> dict[str, Any]:
    result = docker_ops.image_inspect(image)
    main._audit("docker.image_inspect", {"image": image}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_inspect(container: str) -> dict[str, Any]:
    result = docker_ops.container_inspect(container)
    main._audit("docker.container_inspect", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_health(container: str) -> dict[str, Any]:
    result = docker_ops.container_health(container)
    main._audit("docker.container_health", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_logs(container: str, tail: int = 200) -> dict[str, Any]:
    result = docker_ops.container_logs(container, tail)
    main._audit("docker.container_logs", {"container": container, "tail": tail}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def backup_recovery_list(limit: int = 20) -> dict[str, Any]:
    result = recovery_ops.backup_recovery_list(limit)
    main._audit("backup.recovery_list", {"limit": limit}, {"ok": result.get("ok"), "count": result.get("count")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def backup_recovery_find(archive_name: str, query: str, max_results: int = 100) -> dict[str, Any]:
    result = recovery_ops.backup_recovery_find(archive_name, query, max_results)
    main._audit("backup.recovery_find", {"archive_name": archive_name, "query": query, "max_results": max_results}, {"ok": result.get("ok"), "count": result.get("count")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def backup_recovery_preview(archive_name: str, member_path: str, destination: str = "") -> dict[str, Any]:
    result = recovery_ops.backup_recovery_preview(archive_name, member_path, destination)
    main._audit("backup.recovery_preview", {"archive_name": archive_name, "member_path": member_path, "destination": destination}, {"ok": result.get("ok"), "would_overwrite": result.get("would_overwrite")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def backup_recovery_restore_file(archive_name: str, member_path: str, destination: str = "", confirm: str = "") -> dict[str, Any]:
    result = recovery_ops.backup_recovery_restore_file(archive_name, member_path, destination, confirm)
    main._audit("backup.recovery_restore_file", {"archive_name": archive_name, "member_path": member_path, "destination": destination}, {"ok": result.get("ok"), "status": result.get("status"), "operation_id": result.get("operation_id")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def connector_endpoint_check(hostname: str, path: str = "/mcp") -> dict[str, Any]:
    result = recovery_ops.connector_endpoint_check(hostname, path)
    main._audit("recovery.connector_endpoint_check", {"hostname": hostname, "path": path}, {"ok": result.get("ok"), "status_code": result.get("status_code")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def http_asset_probe(hostname: str, path: str, max_bytes: int = 25 * 1024 * 1024) -> dict[str, Any]:
    result = recovery_ops.http_asset_probe(hostname, path, max_bytes)
    main._audit("recovery.http_asset_probe", {"hostname": hostname, "path": path, "max_bytes": max_bytes}, {"ok": result.get("ok"), "status_code": result.get("status_code"), "bytes": result.get("bytes"), "sha256": result.get("sha256")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def proxy_route_inspect(hostname: str) -> dict[str, Any]:
    result = recovery_ops.proxy_route_inspect(hostname)
    main._audit("recovery.proxy_route_inspect", {"hostname": hostname}, {"ok": result.get("ok"), "match_count": result.get("match_count")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def mcp_publication_check(hostname: str, container: str = "") -> dict[str, Any]:
    result = recovery_ops.mcp_publication_check(hostname, container)
    main._audit("recovery.mcp_publication_check", {"hostname": hostname, "container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def hml_route_inspect(route_id: str) -> dict[str, Any]:
    result = recovery_ops.hml_route_inspect(route_id)
    main._audit("routing.hml_route_inspect", {"route_id": route_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def hml_route_activate(route_id: str, confirm: str = "") -> dict[str, Any]:
    result = recovery_ops.hml_route_activate(route_id, confirm)
    main._audit("routing.hml_route_activate", {"route_id": route_id}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


if __name__ == "__main__":
    main.mcp.run(transport="http", host="0.0.0.0", port=8000)

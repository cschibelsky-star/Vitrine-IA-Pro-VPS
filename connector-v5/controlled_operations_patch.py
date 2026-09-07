from __future__ import annotations

"""Recover V5 0.5.13 controlled operations from the preserved 2026-09-06 snapshot.

This layer is intentionally fail-closed. It is applied after marketing_live_patch
and reconstructs the material runtime behavior that existed before Git reconcile.
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"controlled_operations_patch_{label}_match_count:{count}")
    return source.replace(old, new, 1)


def _replace_section(source: str, start: str, end: str, replacement: str, label: str) -> str:
    start_at = source.find(start)
    if start_at < 0:
        raise RuntimeError(f"controlled_operations_patch_{label}_start_missing")
    end_at = source.find(end, start_at)
    if end_at < 0:
        raise RuntimeError(f"controlled_operations_patch_{label}_end_missing")
    return source[:start_at] + replacement.rstrip() + "\n\n\n" + source[end_at:]


def apply(source: str) -> str:
    source = _replace_once(
        source,
        'VERSION = "0.5.11-marketing-live-homologation"',
        'VERSION = "0.5.13-controlled-operations"',
        "version",
    )

    backup_start = '@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_mariadb_backup('
    compose_start = '@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_compose_explicit('
    backup_block = r'''
def _backup_config(project_id: str) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    manifest, workspace, repository = _project_paths(project_id)
    backup = manifest.get("backup", {})
    if not isinstance(backup, dict) or backup.get("enabled") is not True:
        raise PermissionError("backup_not_configured")
    backup_type = str(backup.get("type", "")).strip().lower()
    if backup_type != "mariadb":
        raise ValueError("backup_type_not_supported")
    return manifest, workspace, repository, backup


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_backup_configure(project_id: str, backup_type: str, source_container: str, db_container: str, database: str, expected_host: str = "", directory: str = "backups/database", retention_days: int = 14, min_bytes: int = 512, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    normalized_type = str(backup_type or "").strip().lower()
    if normalized_type != "mariadb":
        return {"ok": False, "error": "backup_type_not_supported", "allowed": ["mariadb"]}
    allowed_container = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    for field, value in {"source_container": source_container, "db_container": db_container}.items():
        normalized = str(value or "").strip()
        if not normalized or any(ch not in allowed_container for ch in normalized):
            return {"ok": False, "error": "invalid_backup_container", "field": field, "project_id": project_id}
    normalized_database = str(database or "").strip()
    if not normalized_database or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in normalized_database):
        return {"ok": False, "error": "invalid_backup_database", "project_id": project_id}
    relative_dir = str(directory or "backups/database").strip().replace("\\", "/")
    if not relative_dir or relative_dir.startswith("/") or ".." in relative_dir.split("/"):
        return {"ok": False, "error": "invalid_backup_directory", "project_id": project_id}
    retention = int(retention_days)
    minimum = int(min_bytes)
    if retention < 0 or retention > 3650:
        return {"ok": False, "error": "invalid_retention_days", "project_id": project_id}
    if minimum < 512 or minimum > 1073741824:
        return {"ok": False, "error": "invalid_backup_min_bytes", "project_id": project_id}
    manifest_path = _manifest_path(project_id)
    manifest = _load_manifest(project_id)
    workspace = Path(str(manifest["workspace_root"])).resolve()
    target_dir = (workspace / relative_dir).resolve()
    if not _within(target_dir, workspace):
        return {"ok": False, "error": "backup_path_blocked", "project_id": project_id}
    manifest["backup"] = {
        "enabled": True,
        "type": normalized_type,
        "source_container": str(source_container).strip(),
        "db_container": str(db_container).strip(),
        "database": normalized_database,
        "expected_host": str(expected_host or db_container).strip(),
        "directory": relative_dir,
        "retention_days": retention,
        "min_bytes": minimum,
        "pre_mutation_required": True,
    }
    _atomic_write_json(manifest_path, manifest)
    result = {"ok": True, "status": "configured", "project_id": project_id, "backup": manifest["backup"]}
    _audit("project_backup_configure", {"project_id": project_id, "type": normalized_type, "database": normalized_database}, {"ok": True, "status": "configured"})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_backup_status(project_id: str) -> dict[str, Any]:
    try:
        _, workspace, _, backup = _backup_config(project_id)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}
    relative_dir = str(backup.get("directory", "backups/database")).strip().replace("\\", "/")
    target_dir = (workspace / relative_dir).resolve()
    if not _within(target_dir, workspace):
        return {"ok": False, "error": "backup_path_blocked", "project_id": project_id}
    return {"ok": True, "project_id": project_id, "enabled": True, "type": "mariadb", "source_container": str(backup.get("source_container", "")), "db_container": str(backup.get("db_container", "")), "database": str(backup.get("database", "")), "directory": relative_dir, "retention_days": int(backup.get("retention_days", 0) or 0), "backup_directory_exists": target_dir.is_dir()}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_docker_status(project_id: str) -> dict[str, Any]:
    manifest, _, repository = _project_paths(project_id)
    docker = manifest.get("docker", {})
    compose_file = str(docker.get("compose_file", "") or "").strip()
    docker_project = str(docker.get("project_name", project_id) or project_id).strip()
    if compose_file:
        try:
            target, relative = _safe_file(project_id, compose_file, True)
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc), "project_id": project_id, "compose_file": compose_file}
        result = _run(["docker", "compose", "-p", docker_project, "-f", str(target), "ps"], repository, timeout=60)
        result.update({"project_id": project_id, "compose_file": relative, "docker_project": docker_project})
        return result
    result = _run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={docker_project}", "--format", "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"], repository, timeout=60)
    result.update({"project_id": project_id, "compose_file": "", "docker_project": docker_project})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_database_backup(project_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    try:
        _, workspace, repository, backup = _backup_config(project_id)
    except (PermissionError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}
    source_container = str(backup.get("source_container", "")).strip()
    db_container = str(backup.get("db_container", "")).strip()
    expected_database = str(backup.get("database", "")).strip()
    expected_host = str(backup.get("expected_host", db_container)).strip()
    inspected = _run(["docker", "inspect", source_container], repository, timeout=30)
    if not inspected.get("ok"):
        return {"ok": False, "error": "source_runtime_unavailable", "project_id": project_id, "detail": inspected}
    try:
        payload = json.loads(inspected.get("stdout") or "[]")
        item = payload[0] if isinstance(payload, list) and payload else {}
        env_map = {}
        for entry in item.get("Config", {}).get("Env", []) or []:
            key, sep, value = str(entry).partition("=")
            if sep:
                env_map[key] = value
    except json.JSONDecodeError:
        return {"ok": False, "error": "source_runtime_inspect_invalid", "project_id": project_id}
    if env_map.get("DB_CONNECTION") not in {"mysql", "mariadb"}:
        return {"ok": False, "error": "database_runtime_mismatch", "key": "DB_CONNECTION", "actual": env_map.get("DB_CONNECTION")}
    if expected_host and env_map.get("DB_HOST") != expected_host:
        return {"ok": False, "error": "database_runtime_mismatch", "key": "DB_HOST", "expected": expected_host, "actual": env_map.get("DB_HOST")}
    if env_map.get("DB_DATABASE") != expected_database:
        return {"ok": False, "error": "database_runtime_mismatch", "key": "DB_DATABASE", "expected": expected_database, "actual": env_map.get("DB_DATABASE")}
    username = env_map.get("DB_USERNAME", "")
    password = env_map.get("DB_PASSWORD", "")
    if not username or not password:
        return {"ok": False, "error": "database_credentials_incomplete", "project_id": project_id}
    relative_dir = str(backup.get("directory", "backups/database")).strip().replace("\\", "/")
    backup_dir = (workspace / relative_dir).resolve()
    if not _within(backup_dir, workspace):
        return {"ok": False, "error": "backup_path_blocked", "project_id": project_id}
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{expected_database}-{stamp}.sql"
    cmd = ["docker", "exec", "-e", "MYSQL_PWD", db_container, "mariadb-dump", "-u", username, "--single-transaction", "--quick", "--routines", "--events", "--triggers", "--hex-blob", "--default-character-set=utf8mb4", expected_database]
    env = {**os.environ, "MYSQL_PWD": password, "LC_ALL": "C.UTF-8"}
    try:
        with target.open("wb") as fh:
            proc = subprocess.run(cmd, cwd=str(repository), stdout=fh, stderr=subprocess.PIPE, timeout=1200, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_execution_failed", "project_id": project_id, "detail": type(exc).__name__}
    if proc.returncode != 0:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_failed", "project_id": project_id, "exit_code": proc.returncode, "stderr": proc.stderr.decode("utf-8", errors="replace")[-4000:]}
    size = target.stat().st_size if target.is_file() else 0
    min_bytes = max(512, int(backup.get("min_bytes", 512) or 512))
    if size < min_bytes:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_too_small", "project_id": project_id, "bytes": size, "min_bytes": min_bytes}
    digest = hashlib.sha256()
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    os.chmod(target, 0o600)
    result = {"ok": True, "status": "created", "project_id": project_id, "database": expected_database, "backup_path": str(target), "bytes": size, "sha256": digest.hexdigest(), "retention_days": int(backup.get("retention_days", 0) or 0)}
    _audit("project_database_backup", {"project_id": project_id, "database": expected_database}, {"ok": True, "backup_path": str(target), "bytes": size, "sha256": result["sha256"]})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_mariadb_backup(project_id: str, confirm: str = "") -> dict[str, Any]:
    return project_database_backup(project_id, confirm)
'''
    source = _replace_section(source, backup_start, compose_start, backup_block, "backup_section")

    activate_start = '@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef activate_hml_route('
    compose_block = r'''
@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_manifest_docker_configure(project_id: str, compose_file: str, docker_project: str = "", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    try:
        project_id = _safe_project_id(project_id)
        manifest_path = _manifest_path(project_id)
        manifest = _load_manifest(project_id)
        _, relative = _safe_file(project_id, compose_file, True)
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "project_id": str(project_id or "").strip()}
    normalized_project = str(docker_project or project_id).strip()
    if not normalized_project or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in normalized_project):
        return {"ok": False, "error": "invalid_docker_project", "project_id": project_id}
    previous = dict(manifest.get("docker", {}) or {})
    manifest["docker"] = {"compose_file": relative, "project_name": normalized_project}
    _atomic_write_json(manifest_path, manifest)
    result = {
        "ok": True,
        "status": "configured",
        "project_id": project_id,
        "docker": manifest["docker"],
        "previous": previous,
    }
    _audit(
        "project_manifest_docker_configure",
        {"project_id": project_id, "compose_file": relative, "docker_project": normalized_project},
        {"ok": True, "status": "configured"},
    )
    return result


CONTROLLED_COMPOSE_POLICY: dict[str, dict[str, Any]] = {
    "vitrine-ia-pro-core": {
        "compose_files": {"docker-compose.core-hml.yml"},
        "services": {"core_db", "core_migrate", "core_seed_providers", "core_seed_agents", "core_app", "core_web"},
        "run_once": {"core_migrate", "core_seed_providers", "core_seed_agents"},
        "build": {"core_app"},
        "up": {"core_db", "core_app", "core_web"},
    },
    "vitrine-ai-pro-factory": {
        "compose_files": {"docker-compose.hml.yml"},
        "services": {"vitrine_factory_hml_db", "vitrine_factory_hml_migrate", "vitrine_factory_hml_app", "vitrine_factory_hml_web", "vitrine_factory_hml_check", "vitrine_factory_hml_dryrun", "vitrine_factory_hml_intake_probe"},
        "run_once": {"vitrine_factory_hml_migrate", "vitrine_factory_hml_intake_probe"},
        "build": {"vitrine_factory_hml_app"},
        "up": {"vitrine_factory_hml_db", "vitrine_factory_hml_app", "vitrine_factory_hml_web"},
    },
    "vps-ops-full-catalog-candidate": {
        "compose_files": {"recovery/full-catalog/docker-compose.snapshot-candidate.yml"},
        "services": {"vps_mcp_snapshot_candidate"},
        "run_once": set(),
        "build": {"vps_mcp_snapshot_candidate"},
        "up": {"vps_mcp_snapshot_candidate"},
    },
    "v5-0-5-13-recovery-validation": {
        "compose_files": {"docker-compose.v5-recovery-candidate.yml"},
        "services": {"connector_v5_recovery_candidate"},
        "run_once": set(),
        "build": {"connector_v5_recovery_candidate"},
        "up": {"connector_v5_recovery_candidate"},
    },
    "vitrine-ai-social-enterprise": {
        "compose_files": {"compose.studio.yml"},
        "services": {"studio_app", "studio_web", "studio_worker", "studio_scheduler"},
        "run_once": set(),
        "build": {"studio_app", "studio_worker", "studio_scheduler"},
        "up": {"studio_app", "studio_web", "studio_worker", "studio_scheduler"},
    },
}


def _controlled_compose_base(project_id: str, compose_file: str) -> tuple[list[str], str, Path]:
    policy = CONTROLLED_COMPOSE_POLICY.get(project_id)
    if policy is None:
        raise PermissionError("controlled_operations_project_not_allowed")
    target, relative = _safe_file(project_id, compose_file, True)
    if relative not in policy["compose_files"]:
        raise PermissionError("controlled_compose_file_not_allowed")
    manifest, _, repository = _project_paths(project_id)
    project_name = str(manifest.get("docker", {}).get("project_name", project_id) or project_id).strip()
    base = ["docker", "compose"]
    runtime_target, _ = _runtime_config(manifest)
    if not runtime_target.is_file():
        return [], relative, repository
    base += ["--env-file", str(runtime_target), "-p", project_name, "-f", str(target)]
    return base, relative, repository


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_compose_service_status(project_id: str, compose_file: str, service: str) -> dict[str, Any]:
    policy = CONTROLLED_COMPOSE_POLICY.get(project_id)
    normalized = str(service or "").strip()
    if policy is None or normalized not in policy["services"]:
        return {"ok": False, "error": "controlled_service_not_allowed", "project_id": project_id, "service": normalized}
    try:
        base, relative, repository = _controlled_compose_base(project_id, compose_file)
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}
    if not base:
        return {"ok": False, "error": "runtime_env_not_configured", "project_id": project_id}
    result = _run(base + ["ps", "-a", normalized], repository, timeout=60)
    result.update({"project_id": project_id, "compose_file": relative, "service": normalized})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_compose_service_logs(project_id: str, compose_file: str, service: str, tail: int = 100) -> dict[str, Any]:
    policy = CONTROLLED_COMPOSE_POLICY.get(project_id)
    normalized = str(service or "").strip()
    if policy is None or normalized not in policy["services"]:
        return {"ok": False, "error": "controlled_service_not_allowed", "project_id": project_id, "service": normalized}
    limit = max(1, min(int(tail), 500))
    try:
        base, relative, repository = _controlled_compose_base(project_id, compose_file)
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}
    if not base:
        return {"ok": False, "error": "runtime_env_not_configured", "project_id": project_id}
    result = _run(base + ["logs", "--no-color", "--tail", str(limit), normalized], repository, timeout=60)
    result.update({"project_id": project_id, "compose_file": relative, "service": normalized, "tail": limit})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_compose_service_execute(project_id: str, compose_file: str, service: str, operation: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    policy = CONTROLLED_COMPOSE_POLICY.get(project_id)
    normalized = str(service or "").strip()
    op = str(operation or "").strip().lower()
    if policy is None or normalized not in policy["services"]:
        return {"ok": False, "error": "controlled_service_not_allowed", "project_id": project_id, "service": normalized}
    if op not in {"up", "build", "run_once"} or normalized not in policy.get(op, set()):
        return {"ok": False, "error": "controlled_operation_not_allowed", "project_id": project_id, "service": normalized, "operation": op}
    try:
        base, relative, repository = _controlled_compose_base(project_id, compose_file)
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}
    if not base:
        return {"ok": False, "error": "runtime_env_not_configured", "project_id": project_id}
    if op == "up":
        cmd = base + ["up", "-d", "--no-deps", "--no-build", normalized]
    elif op == "build":
        cmd = base + ["build", normalized]
    else:
        cmd = base + ["up", "--no-deps", "--no-build", "--abort-on-container-exit", "--exit-code-from", normalized, normalized]
    result = _run(cmd, repository, timeout=1200)
    result.update({"project_id": project_id, "compose_file": relative, "service": normalized, "operation": op})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]:
    action = str(action or "status").strip().lower()
    if action not in {"status", "config"}:
        return {"ok": False, "error": "broad_compose_mutation_disabled", "allowed": ["status", "config"], "use": "project_compose_service_execute"}
    target, relative = _safe_file(project_id, compose_file, True)
    manifest, _, repository = _project_paths(project_id)
    project_name = docker_project.strip() or manifest.get("docker", {}).get("project_name", project_id)
    base = ["docker", "compose"]
    try:
        runtime_target, _ = _runtime_config(manifest)
    except PermissionError as exc:
        if str(exc) != "runtime_keys_not_configured":
            raise
        runtime_target = None
    if runtime_target is not None:
        if not runtime_target.is_file():
            return {"ok": False, "error": "runtime_env_not_configured", "project_id": project_id}
        base += ["--env-file", str(runtime_target)]
    base += ["-p", project_name, "-f", str(target)]
    cmd = base + (["ps"] if action == "status" else ["config", "--no-interpolate"])
    result = _run(cmd, repository, timeout=60)
    result.update({"project_id": project_id, "compose_file": relative, "action": action, "docker_project": project_name})
    return result
'''
    source = _replace_section(source, compose_start, activate_start, compose_block, "compose_section")
    return source

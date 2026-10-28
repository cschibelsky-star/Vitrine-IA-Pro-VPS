"""Narrow, fail-closed overlay for the installed publication-guard image."""
import ast

BRANCH_TOOL_SOURCE = "@mcp.tool(annotations={\"readOnlyHint\": False, \"destructiveHint\": False})\ndef project_manifest_branch_configure(project_id: str, branch: str, expected_current_branch: str, expected_remote_commit: str, confirm: str = \"\") -> dict[str, Any]:\n    \"\"\"Change only the registered branch; never checkout, deploy, or restart.\"\"\"\n    import fcntl\n    import re\n    import tempfile\n    import uuid\n\n    if confirm != \"EXECUTAR\":\n        return {\"ok\": False, \"error\": \"confirmation_required\", \"required\": \"EXECUTAR\"}\n    if not isinstance(branch, str) or not branch or branch != branch.strip() or branch.startswith(\"-\"):\n        return {\"ok\": False, \"error\": \"invalid_branch\"}\n    if not re.fullmatch(r\"[0-9a-f]{40}\", expected_remote_commit or \"\"):\n        return {\"ok\": False, \"error\": \"invalid_expected_remote_commit\"}\n    if not expected_current_branch:\n        return {\"ok\": False, \"error\": \"expected_current_branch_required\"}\n    project_id = _safe_project_id(project_id)\n    manifest_path = _manifest_path(project_id)\n    # The lock serializes this operation. Existing unrelated manifest writers do\n    # not share it; the byte comparison below also detects intervening writes.\n    with manifest_path.with_suffix(\".branch.lock\").open(\"a\", encoding=\"utf-8\") as lock:\n        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)\n        manifest, _, repository = _project_paths(project_id)\n        original = manifest_path.read_bytes()\n        if json.loads(original) != manifest:\n            return {\"ok\": False, \"error\": \"manifest_changed_during_read\"}\n        previous = manifest.get(\"repository\", {}).get(\"branch\")\n        if previous != expected_current_branch:\n            return {\"ok\": False, \"error\": \"official_branch_conflict\", \"current_branch\": previous}\n        if not (repository / \".git\").is_dir():\n            return {\"ok\": False, \"error\": \"repository_not_git\"}\n        checked = subprocess.run([\"git\", \"check-ref-format\", \"--branch\", branch], cwd=repository, capture_output=True, text=True, timeout=15, check=False)\n        if checked.returncode != 0:\n            return {\"ok\": False, \"error\": \"invalid_branch\"}\n        # Use the registered URL, not a potentially different local origin.\n        remote_url = _validated_repository_url(manifest[\"repository\"][\"url\"])\n        remote = subprocess.run([\"git\", \"ls-remote\", \"--exit-code\", \"--heads\", remote_url, \"refs/heads/\" + branch], cwd=repository, capture_output=True, text=True, timeout=30, check=False)\n        expected_line = expected_remote_commit + \"\\trefs/heads/\" + branch\n        if remote.returncode != 0 or remote.stdout.strip() != expected_line:\n            # Do not return stderr: authentication diagnostics may be sensitive.\n            return {\"ok\": False, \"error\": \"remote_branch_commit_not_verified\"}\n        if previous == branch:\n            return {\"ok\": True, \"status\": \"unchanged\", \"project_id\": project_id, \"branch\": branch, \"verified_remote_commit\": expected_remote_commit}\n        stamp = datetime.now(timezone.utc).strftime(\"%Y%m%dT%H%M%S%fZ\")\n        backup = manifest_path.with_name(manifest_path.name + \".bak-branch-\" + stamp + \"-\" + uuid.uuid4().hex)\n        # Exclusive backup creation precedes any write to the official record.\n        with backup.open(\"xb\") as handle:\n            os.chmod(backup, 0o600)\n            handle.write(original)\n            handle.flush()\n            os.fsync(handle.fileno())\n        payload = {\"project_id\": project_id, \"previous_branch\": previous, \"branch\": branch, \"verified_remote_commit\": expected_remote_commit, \"backup_name\": backup.name}\n        _audit(\"project_manifest_branch_configure\", payload, {\"ok\": True, \"status\": \"prepared\"})\n        manifest[\"repository\"][\"branch\"] = branch\n        temporary = None\n        try:\n            with tempfile.NamedTemporaryFile(mode=\"w\", encoding=\"utf-8\", dir=manifest_path.parent, prefix=\".branch-\", delete=False) as handle:\n                temporary = Path(handle.name)\n                os.chmod(temporary, manifest_path.stat().st_mode & 0o777)\n                json.dump(manifest, handle, ensure_ascii=False, indent=2)\n                handle.write(\"\\n\")\n                handle.flush()\n                os.fsync(handle.fileno())\n            if manifest_path.read_bytes() != original:\n                return {\"ok\": False, \"error\": \"manifest_changed_before_write\", \"backup_name\": backup.name}\n            os.replace(temporary, manifest_path)\n        finally:\n            if temporary is not None:\n                temporary.unlink(missing_ok=True)\n        result = {\"ok\": True, \"status\": \"configured\", **payload}\n        try:\n            _audit(\"project_manifest_branch_configure\", payload, {\"ok\": True, \"status\": \"configured\"})\n        except OSError:\n            # The write already committed: report that fact, do not invite retry.\n            result[\"audit_completion_failed\"] = True\n        return result"
RUNTIME_PATH_SOURCE = "def _controlled_runtime_env_path(manifest: dict[str, Any]) -> Path:\n    # Compose consumes an existing file; allowed_keys authorizes secret editing,\n    # not status/build/up. Never read or expose the file contents here.\n    runtime = manifest.get(\"runtime\", {}) or {}\n    relative = str(runtime.get(\"env_file\", \".env.runtime\")).strip().replace(chr(92), \"/\")\n    if not relative or relative.startswith(\"/\") or \"..\" in relative.split(\"/\"):\n        raise ValueError(\"invalid_runtime_env_file\")\n    workspace = _validated_workspace_root(str(manifest[\"workspace_root\"]))\n    target = (workspace / relative).resolve()\n    if not _within(target, workspace):\n        raise PermissionError(\"runtime_env_outside_workspace\")\n    return target"

def _function(source, name):
    matches = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) > 1:
        raise ValueError("registry_overlay_duplicate_" + name)
    return matches[0] if matches else None

def _same(left, right):
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)

def apply(source):
    base = _function(source, "_controlled_compose_base")
    if base is None:
        raise ValueError("registry_overlay_compose_base_missing")
    lines = source.splitlines(keepends=True)
    section = "".join(lines[base.lineno - 1:base.end_lineno])
    old = "    runtime_target, _ = _runtime_config(manifest)"
    new = "    runtime_target = _controlled_runtime_env_path(manifest)"
    if section.count(old) == 1 and section.count(new) == 0:
        section = section.replace(old, new, 1)
        source = "".join(lines[:base.lineno - 1]) + section + "".join(lines[base.end_lineno:])
    elif section.count(new) != 1 or section.count(old) != 0:
        raise ValueError("registry_overlay_compose_anchor_mismatch")
    for name, addition in (
        ("_controlled_runtime_env_path", RUNTIME_PATH_SOURCE),
        ("project_manifest_branch_configure", BRANCH_TOOL_SOURCE),
    ):
        existing = _function(source, name)
        expected = _function(addition, name)
        if existing is None:
            source += "\n\n" + addition + "\n"
        elif not _same(existing, expected):
            raise ValueError("registry_overlay_existing_definition_conflict_" + name)
    compile(source, "<registry-runtime-overlay>", "exec")
    return source

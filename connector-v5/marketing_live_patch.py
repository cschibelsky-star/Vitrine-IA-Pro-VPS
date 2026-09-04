from __future__ import annotations

"""Startup patch for the gated Marketing Agents Gemini live homologation.

This patch is intentionally narrow and fail-closed. It upgrades the validated
0.5.10 PHP runner to 0.5.11 without exposing a generic shell operation.
Provenance: validated local commit 27ca2a6a8ff5c173b54383c09d6c29aee37fd4d0.
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"marketing_live_patch_{label}_match_count:{count}")
    return source.replace(old, new, 1)


def apply(source: str) -> str:
    source = _replace_once(
        source,
        'VERSION = "0.5.10-project-phpunit-runner-hardened"',
        'VERSION = "0.5.11-marketing-live-homologation"',
        "version",
    )

    source = _replace_once(
        source,
        '''    commands = {
        "tests_marketing": "php vendor/bin/phpunit tests/Unit/Marketing --colors=never",
        "migrate_pretend": "php artisan migrate --pretend --no-interaction",
    }''',
        '''    commands = {
        "tests_marketing": "php vendor/bin/phpunit tests/Unit/Marketing --colors=never",
        "migrate_pretend": "php artisan migrate --pretend --no-interaction",
        "marketing_gemini_live": "php vendor/bin/phpunit tests/Unit/Marketing/MarketingGeminiLiveHomologationTest.php --colors=never",
    }''',
        "commands",
    )

    source = _replace_once(
        source,
        '''    _, _, repository = _project_paths(project_id)
    if not (repository / "artisan").is_file() or not (repository / "composer.json").is_file():''',
        '''    manifest, _, repository = _project_paths(project_id)
    if not (repository / "artisan").is_file() or not (repository / "composer.json").is_file():''',
        "manifest",
    )

    source = _replace_once(
        source,
        '''    if operation == "tests_marketing":
        composer_lock = repository / "composer.lock"''',
        '''    if operation in {"tests_marketing", "marketing_gemini_live"}:
        if operation == "marketing_gemini_live" and project_id != "vitrine-marketing-agents-core-hml":
            return {"ok": False, "error": "marketing_live_validation_not_allowed_for_project", "project_id": project_id}
        composer_lock = repository / "composer.lock"''',
        "dependency_scope",
    )

    source = _replace_once(
        source,
        '''    extra_mounts: list[str] = []

    bootstrap = (''',
        '''    extra_mounts: list[str] = []
    network_args: list[str] = ["--network", "none"]
    runtime_env_args: list[str] = []
    if operation == "marketing_gemini_live":
        try:
            runtime_target, _ = _runtime_config(manifest)
        except (ValueError, PermissionError) as exc:
            return {"ok": False, "error": "marketing_runtime_config_invalid", "detail": str(exc), "operation": operation}
        if not runtime_target.is_file():
            return {"ok": False, "error": "marketing_runtime_env_missing", "operation": operation}
        network_args = []
        runtime_env_args = ["--env-file", str(runtime_target), "--env", "MARKETING_LIVE_HOMOLOGATION=1"]

    bootstrap = (''',
        "runtime_args",
    )

    source = _replace_once(
        source,
        '''    result = _run([
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", "768m",
        "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--tmpfs", "/work:rw,nosuid,nodev,size=768m",
        "--env", "APP_ENV=testing",
        "--env", "APP_DEBUG=false",
        "--env", "APP_KEY=base64:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        "--env", "DB_CONNECTION=sqlite",
        "--env", "DB_DATABASE=:memory:",
        "--env", "CACHE_STORE=array",
        "--env", "SESSION_DRIVER=array",
        "--env", "QUEUE_CONNECTION=sync",
        "--entrypoint", "sh",
        "--mount", f"type=bind,src={repository},dst=/source,readonly",
    ] + extra_mounts + [''',
        '''    result = _run([
        "docker", "run", "--rm",
    ] + network_args + [
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", "768m",
        "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--tmpfs", "/work:rw,nosuid,nodev,size=768m",
        "--env", "APP_ENV=testing",
        "--env", "APP_DEBUG=false",
        "--env", "APP_KEY=base64:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        "--env", "DB_CONNECTION=sqlite",
        "--env", "DB_DATABASE=:memory:",
        "--env", "CACHE_STORE=array",
        "--env", "SESSION_DRIVER=array",
        "--env", "QUEUE_CONNECTION=sync",
    ] + runtime_env_args + [
        "--entrypoint", "sh",
        "--mount", f"type=bind,src={repository},dst=/source,readonly",
    ] + extra_mounts + [''',
        "docker_run",
    )

    return source

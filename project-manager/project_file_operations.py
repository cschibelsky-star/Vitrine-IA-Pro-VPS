from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PHP_LINT_TIMEOUT = int(os.getenv("PROJECT_PHP_LINT_TIMEOUT", "15"))
MAX_WRITE_BYTES = int(os.getenv("PROJECT_MAX_WRITE_BYTES", "1048576"))

ALLOWED_PROJECT_ROOTS = {
    "admin",
    "app",
    "bootstrap",
    "config",
    "database",
    "includes",
    "public",
    "resources",
    "routes",
    "storage/app/factory",
    "tests",
}
ALLOWED_PROJECT_FILES = {
    "artisan",
    "composer.json",
    "composer.lock",
    "package.json",
    "package-lock.json",
    "phpunit.xml",
    "vite.config.js",
    "README.md",
    "AGENTS.md",
    "docker-compose.app.yml",
}
TEXT_SUFFIXES = {
    ".php", ".json", ".md", ".txt", ".yml", ".yaml", ".xml",
    ".js", ".ts", ".css", ".scss", ".vue", ".sql", ".sh",
}
BLOCKED_NAMES = {
    ".env", "auth.json", "credentials.json", "oauth.json",
    "id_rsa", "id_ed25519",
}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3"}
SENSITIVE_FRAGMENTS = {"secret", "credential", "private"}
BLOCKED_DIRECTORIES = {
    ".git", "vendor", "node_modules", "__pycache__", "bootstrap/cache",
    "storage/framework", "storage/logs", "storage/oauth", "secrets",
    "credentials", "private",
}


class ProjectFileOperationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _fail(status_code: int, detail: str) -> None:
    raise ProjectFileOperationError(status_code, detail)


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _normalize_project_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if (
        not raw
        or raw.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:/", raw)
        or ":" in raw
        or any(ord(character) < 32 for character in raw)
    ):
        _fail(422, "invalid_project_path")
    parts = tuple(part for part in raw.split("/") if part not in ("", "."))
    if not parts or ".." in parts or "\x00" in raw:
        _fail(422, "invalid_project_path")
    return "/".join(parts)


def _is_allowed_project_scope(relative_path: str) -> bool:
    if relative_path in ALLOWED_PROJECT_FILES:
        return True
    return any(
        relative_path == root or relative_path.startswith(root + "/")
        for root in ALLOWED_PROJECT_ROOTS
    )


def _is_sensitive_project_path(relative_path: str, candidate: Path) -> bool:
    parts = [part.lower() for part in relative_path.split("/")]
    name = candidate.name.lower()
    if name in BLOCKED_NAMES or name.startswith(".env") or candidate.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    joined = "/".join(parts)
    if any(fragment in part for part in parts for fragment in SENSITIVE_FRAGMENTS):
        return True
    return any(
        joined == blocked
        or joined.startswith(blocked + "/")
        or f"/{blocked}/" in f"/{joined}/"
        for blocked in BLOCKED_DIRECTORIES
    )


def _is_text_path(relative_path: str, candidate: Path) -> bool:
    if relative_path in ALLOWED_PROJECT_FILES:
        return True
    name = candidate.name.lower()
    if name.endswith(".blade.php") or candidate.suffix.lower() in TEXT_SUFFIXES:
        return True
    return re.fullmatch(r".+\.php\.bak-[a-z0-9._-]+", name) is not None


def _has_symlink_component(repository: Path, relative_path: str) -> bool:
    candidate = repository
    for part in relative_path.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            return True
        if not candidate.exists():
            break
    return False


def safe_project_file(
    repository: Path,
    value: Any,
    *,
    must_exist: bool,
) -> tuple[str, Path]:
    repository = repository.resolve()
    relative = _normalize_project_path(value)
    if not _is_allowed_project_scope(relative):
        _fail(403, "project_path_scope_blocked")
    if _has_symlink_component(repository, relative):
        _fail(403, "project_symlink_blocked")
    candidate = (repository / relative).resolve()
    if not is_within(candidate, repository):
        _fail(403, "project_path_outside_repository")
    if _is_sensitive_project_path(relative, candidate):
        _fail(403, "sensitive_path_blocked")
    if not _is_text_path(relative, candidate):
        _fail(403, "non_text_path_blocked")
    if must_exist and not candidate.is_file():
        _fail(404, "project_file_not_found")
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_file()):
        _fail(403, "project_file_type_blocked")
    return relative, candidate


def write_project_file(
    repository: Path,
    path: str,
    content: str,
    *,
    backup: bool = True,
    confirm: str = "",
    audit_callback: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if confirm != "EXECUTAR":
        _fail(422, "confirmation_required")
    relative, target = safe_project_file(repository, path, must_exist=False)
    encoded = content.encode("utf-8")
    if b"\x00" in encoded:
        _fail(422, "binary_content_blocked")
    if len(encoded) > MAX_WRITE_BYTES:
        _fail(413, "content_too_large")

    target.parent.mkdir(parents=True, exist_ok=True)
    if not is_within(target.parent.resolve(), repository.resolve()):
        _fail(403, "project_parent_outside_repository")

    backup_relative: str | None = None
    file_mode = 0o644
    if target.is_file():
        file_mode = stat.S_IMODE(target.stat().st_mode)
    if backup and target.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = target.with_name(f".{target.name}.bak-{stamp}")
        shutil.copy2(target, backup_path)
        backup_relative = backup_path.relative_to(repository).as_posix()

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.chmod(temporary_path, file_mode)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    result = {
        "ok": True,
        "status": "written",
        "path": relative,
        "backup": backup_relative,
        "backup_created": backup_relative is not None,
        "bytes_written": len(encoded),
    }
    if audit_callback is not None:
        audit_callback({"path": relative, "backup": backup}, result)
    return result


def _sanitize_lint_output(
    output: str,
    repository: Path,
    target: Path,
    relative_path: str,
) -> str:
    sanitized = output.replace(str(target), relative_path)
    sanitized = sanitized.replace(target.as_posix(), relative_path)
    sanitized = sanitized.replace(str(repository), "<project>")
    sanitized = sanitized.replace(repository.as_posix(), "<project>")
    sanitized = "".join(
        character if character in "\n\t" or ord(character) >= 32 else "?"
        for character in sanitized
    )
    return sanitized[-10000:]


def php_lint_project_file(
    repository: Path,
    path: str,
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: int = PHP_LINT_TIMEOUT,
) -> dict[str, Any]:
    relative, target = safe_project_file(repository, path, must_exist=True)
    if target.suffix.lower() != ".php":
        _fail(422, "php_file_required")
    try:
        proc = run_process(
            ["php", "-l", str(target)],
            cwd=str(repository),
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={"PATH": os.getenv("PATH", ""), "LC_ALL": "C.UTF-8"},
        )
        output = _sanitize_lint_output(
            proc.stdout + proc.stderr,
            repository,
            target,
            relative,
        )
        success = proc.returncode == 0
        return {
            "ok": success,
            "path": relative,
            "success": success,
            "exit_code": proc.returncode,
            "stdout": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "path": relative,
            "success": False,
            "exit_code": 124,
            "stdout": "timeout",
        }
    except OSError:
        return {
            "ok": False,
            "path": relative,
            "success": False,
            "exit_code": 127,
            "stdout": "php_lint_unavailable",
        }

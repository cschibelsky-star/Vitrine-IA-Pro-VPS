from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from project_file_operations import (
    PHP_LINT_TIMEOUT,
    ProjectFileOperationError,
    php_lint_project_file,
    write_project_file,
)

def _blocked(call: Callable[[], Any], detail: str | None = None) -> None:
    try:
        call()
    except ProjectFileOperationError as exc:
        if detail is not None:
            assert exc.detail == detail
        return
    raise AssertionError("unsafe project path was accepted")


def _audit_writer(audit_log: Path) -> Callable[[dict[str, Any], dict[str, Any]], None]:
    def write(payload: dict[str, Any], result: dict[str, Any]) -> None:
        safe_record = {
            "action": "project_write_file",
            "payload": payload,
            "result": result,
        }
        with audit_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_record) + "\n")

    return write


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="project-file-operations-") as temp:
        base = Path(temp)
        repository = base / "repository"
        audit_log = base / "audit.jsonl"
        repository.mkdir()

        secret_content = "<?php\n// FILE_CONTENT_MUST_NOT_BE_LOGGED\nreturn 1;\n"
        relative_path = "app/Services/SafeService.php"
        first = write_project_file(
            repository,
            relative_path,
            secret_content,
            confirm="EXECUTAR",
            audit_callback=_audit_writer(audit_log),
        )
        target = repository / relative_path
        assert first["ok"] is True
        assert first["path"] == relative_path
        assert first["backup"] is None
        assert first["backup_created"] is False
        assert first["bytes_written"] == len(secret_content.encode("utf-8"))
        assert target.read_text(encoding="utf-8") == secret_content
        print("PROJECT_WRITE_WITHIN_ROOT=PASS")

        replacement = "<?php\nreturn 2;\n"
        second = write_project_file(
            repository,
            relative_path,
            replacement,
            confirm="EXECUTAR",
        )
        assert second["backup"] is not None
        assert second["backup_created"] is True
        backup = repository / second["backup"]
        assert backup.is_file()
        assert backup.read_text(encoding="utf-8") == secret_content
        assert target.read_text(encoding="utf-8") == replacement
        print("PROJECT_WRITE_BACKUP=PASS")
        print("PROJECT_SECOND_WRITE=PASS")

        def write(path: str) -> None:
            write_project_file(repository, path, "blocked", confirm="EXECUTAR")

        _blocked(lambda: write("../escape.php"))
        _blocked(lambda: write(".env"))
        _blocked(lambda: write("vendor/package/file.php"))
        _blocked(lambda: write("config/client_secret.php"))
        _blocked(lambda: write(str((base / "outside.php").resolve())))
        _blocked(
            lambda: write_project_file(repository, "app/no-confirm.php", "blocked"),
            "confirmation_required",
        )
        symlink_path = repository / "app" / "linked.php"
        try:
            symlink_path.symlink_to(target)
        except OSError:
            pass
        else:
            _blocked(lambda: write("app/linked.php"), "project_symlink_blocked")
        print("PROJECT_UNSAFE_PATHS_BLOCKED=PASS")

        valid = repository / "app" / "valid.php"
        invalid = repository / "app" / "invalid.php"
        text_file = repository / "app" / "notes.txt"
        valid.write_text("<?php return 1;\n", encoding="utf-8")
        invalid.write_text("<?php syntax error\n", encoding="utf-8")
        text_file.write_text("plain text\n", encoding="utf-8")
        calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            returncode = 255 if argv[-1].endswith("invalid.php") else 0
            output = "PHP Parse error" if returncode else "No syntax errors detected"
            return subprocess.CompletedProcess(argv, returncode, output, "")

        lint_valid = php_lint_project_file(
            repository,
            "app/valid.php",
            run_process=fake_run,
        )
        lint_invalid = php_lint_project_file(
            repository,
            "app/invalid.php",
            run_process=fake_run,
        )
        def fake_timeout(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        lint_timeout = php_lint_project_file(
            repository,
            "app/valid.php",
            run_process=fake_timeout,
        )
        call_count = len(calls)
        _blocked(
            lambda: php_lint_project_file(
                repository,
                "app/notes.txt",
                run_process=fake_run,
            ),
            "php_file_required",
        )
        assert len(calls) == call_count
        assert lint_valid["success"] is True and lint_valid["exit_code"] == 0
        assert lint_invalid["ok"] is False
        assert lint_invalid["success"] is False and lint_invalid["exit_code"] == 255
        assert lint_timeout["success"] is False and lint_timeout["exit_code"] == 124
        for argv, kwargs in calls:
            assert argv == ["php", "-l", argv[2]]
            assert Path(argv[2]).is_file()
            assert kwargs["shell"] is False
            assert kwargs["timeout"] == PHP_LINT_TIMEOUT
        print("PROJECT_PHP_LINT_VALID=PASS")
        print("PROJECT_PHP_LINT_SYNTAX_ERROR=PASS")
        print("PROJECT_PHP_LINT_NON_PHP_BLOCKED=PASS")
        print("PROJECT_PHP_LINT_TIMEOUT=PASS")
        print("PROJECT_NO_ARBITRARY_SHELL=PASS")

        assert secret_content not in audit_log.read_text(encoding="utf-8")
        assert str(repository) not in lint_valid["stdout"]
        print("PROJECT_SAFE_AUDIT=PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import HTTPException

import project_explicit_operations as module


def expect_http(status: int, detail: str, func) -> None:
    try:
        func()
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
        assert exc.detail == detail, (exc.status_code, exc.detail)
    else:
        raise AssertionError(f"expected_http_{status}_{detail}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repository = Path(tmp)
        (repository / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        (repository / "docker-compose.app.yml").write_text(
            "services:\n  app:\n    image: alpine:3.20\n    command: ['sleep','3600']\n",
            encoding="utf-8",
        )

        module.repository_for = lambda project_id: repository
        module.load_manifest = lambda project_id: {"docker": {"project_name": "explicit-lab"}}

        read = module.project_file_read_safe(
            module.ProjectReadSafeRequest(
                project_id="lab",
                path="README.md",
                start_line=2,
                end_line=3,
            )
        )
        assert read["ok"] is True
        assert read["content"] == "beta\ngamma"
        print("READ_SAFE=OK")

        expect_http(
            403,
            "confirmation_required",
            lambda: module.project_file_patch_text(
                module.ProjectPatchTextRequest(
                    project_id="lab",
                    path="README.md",
                    old="beta",
                    new="BETA",
                    confirm="",
                )
            ),
        )
        print("PATCH_CONFIRM_GUARD=OK")

        patch = module.project_file_patch_text(
            module.ProjectPatchTextRequest(
                project_id="lab",
                path="README.md",
                old="beta",
                new="BETA",
                confirm="EXECUTAR",
            )
        )
        assert patch["ok"] is True
        assert patch["replacements"] == 1
        assert (repository / "README.md").read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
        assert (repository / patch["backup"]).is_file()
        print("PATCH_TEXT=OK")
        print("PATCH_BACKUP=OK")

        (repository / "README.md").write_text("same\nsame\n", encoding="utf-8")
        expect_http(
            409,
            "old_text_not_unique",
            lambda: module.project_file_patch_text(
                module.ProjectPatchTextRequest(
                    project_id="lab",
                    path="README.md",
                    old="same",
                    new="changed",
                    confirm="EXECUTAR",
                )
            ),
        )
        print("PATCH_UNIQUENESS_GUARD=OK")

        captured: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path):
            captured.append(command)
            return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

        module.run = fake_run
        module.audit = lambda *args, **kwargs: None

        status = module.project_compose_explicit(
            module.ProjectComposeExplicitRequest(
                project_id="lab",
                compose_file="docker-compose.app.yml",
                action="status",
            )
        )
        assert status["ok"] is True
        assert captured[-1][-1] == "ps"
        print("COMPOSE_STATUS_COMMAND=OK")

        config = module.project_compose_explicit(
            module.ProjectComposeExplicitRequest(
                project_id="lab",
                compose_file="docker-compose.app.yml",
                action="config",
            )
        )
        assert config["ok"] is True
        assert captured[-1][-1] == "config"
        print("COMPOSE_CONFIG_COMMAND=OK")

        expect_http(
            403,
            "confirmation_required",
            lambda: module.project_compose_explicit(
                module.ProjectComposeExplicitRequest(
                    project_id="lab",
                    compose_file="docker-compose.app.yml",
                    action="up",
                )
            ),
        )
        print("COMPOSE_UP_CONFIRM_GUARD=OK")

        up = module.project_compose_explicit(
            module.ProjectComposeExplicitRequest(
                project_id="lab",
                compose_file="docker-compose.app.yml",
                action="up",
                confirm="EXECUTAR",
            )
        )
        assert up["ok"] is True
        assert captured[-1][-3:] == ["-d", "--build"] or captured[-1][-3:] == ["up", "-d", "--build"]
        assert captured[-1][-3:] == ["up", "-d", "--build"]
        print("COMPOSE_UP_COMMAND=OK")

        expect_http(
            422,
            "invalid_compose_file",
            lambda: module.project_compose_explicit(
                module.ProjectComposeExplicitRequest(
                    project_id="lab",
                    compose_file="../docker-compose.yml",
                    action="status",
                )
            ),
        )
        print("COMPOSE_PATH_GUARD=OK")

    print("PROJECT_EXPLICIT_FUNCTIONAL=OK")


if __name__ == "__main__":
    main()

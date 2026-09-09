from __future__ import annotations

import hashlib
from typing import Any

import main


def laravel_test_v2(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)

    if not (repository / "artisan").is_file() or not (repository / "composer.lock").is_file():
        return {"ok": False, "error": "laravel_project_required"}

    if not main.PHP_RUNNER_IMAGE or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-"
        for ch in main.PHP_RUNNER_IMAGE
    ):
        return {"ok": False, "error": "php_runner_image_invalid"}

    image_check = main._run(["docker", "image", "inspect", main.PHP_RUNNER_IMAGE], repository, timeout=30)
    if not image_check.get("ok"):
        return {"ok": False, "error": "php_runner_image_unavailable", "runtime_image": main.PHP_RUNNER_IMAGE}

    lock_hash = hashlib.sha256((repository / "composer.lock").read_bytes()).hexdigest()[:12]
    project_tag = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:8]
    dependency_image = f"vitrine-super-laravel-test:{project_tag}-{lock_hash}"

    dependency_check = main._run(["docker", "image", "inspect", dependency_image], repository, timeout=30)
    if not dependency_check.get("ok"):
        dockerfile = (
            f"FROM {main.PHP_RUNNER_IMAGE}\n"
            "USER root\n"
            "WORKDIR /var/www/html\n"
            "COPY composer.json composer.lock ./\n"
            "RUN composer install --no-interaction --prefer-dist --no-progress --no-scripts --no-plugins\n"
        )
        built = main._run(
            ["docker", "build", "-t", dependency_image, "-f", "-", str(repository)],
            repository,
            timeout=1200,
            input_text=dockerfile,
        )
        if not built.get("ok"):
            return {"ok": False, "error": "laravel_test_dependency_build_failed", "detail": built}

    bootstrap = (
        "set -eu; "
        "mkdir -p /work/project; "
        "cp -R /var/www/html/. /work/project/; "
        "find /source -mindepth 1 -maxdepth 1 ! -name .git -exec cp -R {} /work/project/ \\;; "
        "cd /work/project; "
        "mkdir -p storage/framework/cache storage/framework/sessions storage/framework/views bootstrap/cache; "
        "chmod -R u+rwX storage/framework bootstrap/cache; "
        "test -w storage/framework/cache; "
        "test -w storage/framework/views; "
        "test -w bootstrap/cache; "
        "php artisan test --colors=never"
    )

    result = main._run(
        [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "128",
            "--memory", "768m",
            "--cpus", "1",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m",
            "--tmpfs", "/work:rw,nosuid,nodev,size=768m",
            "--env", "TMPDIR=/tmp",
            "--env", "APP_ENV=testing",
            "--env", "APP_DEBUG=false",
            "--env", "APP_KEY=base64:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
            "--env", "DB_CONNECTION=sqlite",
            "--env", "DB_DATABASE=:memory:",
            "--env", "CACHE_STORE=array",
            "--env", "SESSION_DRIVER=array",
            "--env", "QUEUE_CONNECTION=sync",
            "--env", "VIEW_COMPILED_PATH=/work/project/storage/framework/views",
            "--entrypoint", "sh",
            "--mount", f"type=bind,src={repository},dst=/source,readonly",
            dependency_image,
            "-lc", bootstrap,
        ],
        repository,
        timeout=900,
    )

    result.update(
        {
            "project_id": project_id,
            "runtime": "ephemeral_container_v2",
            "runtime_image": dependency_image,
        }
    )
    main._audit(
        "laravel.test_v2",
        {"project_id": project_id},
        {"ok": result.get("ok"), "exit_code": result.get("exit_code"), "runtime_image": dependency_image},
    )
    return result

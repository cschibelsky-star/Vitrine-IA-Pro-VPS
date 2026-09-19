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
        "umask 000; "
        "mkdir -p /work/project; "
        "cp -R /var/www/html/. /work/project/; "
        "find /source -mindepth 1 -maxdepth 1 ! -name .git -exec cp -R {} /work/project/ \\;; "
        "cd /work/project; "
        "mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views bootstrap/cache; "
        "chmod -R a+rwX storage bootstrap/cache; "
        "test -w storage/framework/cache; "
        "test -w storage/framework/cache/data; "
        "test -w storage/framework/views; "
        "test -w bootstrap/cache; "
        "test -w /tmp; "
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
            "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=64m",
            "--tmpfs", "/work:rw,nosuid,nodev,mode=1777,size=768m",
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
            "--env", "APP_SERVICES_CACHE=/tmp/services.php",
            "--env", "APP_PACKAGES_CACHE=/tmp/packages.php",
            "--env", "APP_CONFIG_CACHE=/tmp/config.php",
            "--env", "APP_ROUTES_CACHE=/tmp/routes.php",
            "--env", "APP_EVENTS_CACHE=/tmp/events.php",
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


def _resolve_laravel_container(project_id: str, service: str) -> tuple[dict[str, Any], Any, Any] | tuple[dict[str, Any], None, None]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    docker = project.get("docker", {})
    compose_file = str(docker.get("compose_file") or docker.get("compose") or "").strip()
    docker_project = str(docker.get("project_name") or docker.get("project") or project_id).strip()
    service = str(service or "").strip()
    if not compose_file:
        return {"ok": False, "error": "compose_file_not_configured", "project_id": project_id}, None, None
    if not service or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in service):
        return {"ok": False, "error": "service_required_or_invalid", "project_id": project_id}, None, None
    compose_path = (repository / compose_file).resolve()
    try:
        compose_path.relative_to(repository.resolve())
    except ValueError:
        return {"ok": False, "error": "compose_file_outside_repository", "project_id": project_id}, None, None
    if not compose_path.is_file():
        return {"ok": False, "error": "compose_file_not_found", "project_id": project_id, "compose_file": compose_file}, None, None
    lookup = main._run(
        ["docker", "compose", "-p", docker_project, "-f", str(compose_path), "ps", "-q", service],
        repository,
        timeout=30,
    )
    container = str(lookup.get("stdout", "")).strip()
    if not lookup.get("ok") or not container:
        fallback = main._run(
            [
                "docker", "ps", "-q",
                "--filter", f"label=com.docker.compose.project={docker_project}",
                "--filter", f"label=com.docker.compose.service={service}",
            ],
            repository,
            timeout=30,
        )
        container = str(fallback.get("stdout", "")).strip().splitlines()[0] if fallback.get("ok") and str(fallback.get("stdout", "")).strip() else ""
    if not container:
        return {"ok": False, "error": "service_container_not_running", "project_id": project_id, "service": service}, None, None
    return {"ok": True, "container": container, "service": service}, repository, container


def route_list(project_id: str, service: str, path_prefix: str = "") -> dict[str, Any]:
    resolved, repository, container = _resolve_laravel_container(project_id, service)
    if not resolved.get("ok"):
        return resolved
    prefix = str(path_prefix or "").strip().strip("/")
    args = ["docker", "exec", str(container), "php", "artisan", "route:list", "--json", "--no-ansi"]
    result = main._run(args, repository, timeout=60)
    if not result.get("ok"):
        result.update({"project_id": project_id, "service": service})
        return result
    try:
        routes = main.json.loads(str(result.get("stdout", "")).strip() or "[]")
    except main.json.JSONDecodeError:
        return {"ok": False, "error": "invalid_route_list_json", "project_id": project_id, "service": service}
    if prefix:
        routes = [route for route in routes if str(route.get("uri", "")).lstrip("/").startswith(prefix)]
    payload = {"ok": True, "project_id": project_id, "service": service, "path_prefix": prefix, "count": len(routes), "routes": routes}
    main._audit("laravel.route_list", {"project_id": project_id, "service": service, "path_prefix": prefix}, {"ok": True, "count": len(routes)})
    return payload


def admin_access_status(project_id: str, email: str, service: str) -> dict[str, Any]:
    email = str(email or "").strip().lower()
    resolved, repository, container = _resolve_laravel_container(project_id, service)
    if not resolved.get("ok"):
        return resolved
    if not email or "@" not in email or len(email) > 254:
        return {"ok": False, "error": "invalid_email", "project_id": project_id}
    code = r'''
require "/var/www/html/vendor/autoload.php";
$app = require "/var/www/html/bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$u = App\Models\User::where("email", getenv("VITRINE_ADMIN_EMAIL"))->first();
if (!$u) { echo json_encode(["ok"=>false,"error"=>"user_not_found"]); exit(2); }
echo json_encode(["ok"=>true,"email"=>$u->email,"role"=>$u->role,"status"=>$u->status,"is_active"=>(bool)($u->is_active ?? false)]);
'''
    result = main._run(
        ["docker", "exec", "-e", f"VITRINE_ADMIN_EMAIL={email}", str(container), "php", "-r", code],
        repository,
        timeout=30,
    )
    try:
        payload = main.json.loads(str(result.get("stdout", "")).strip() or "{}")
    except main.json.JSONDecodeError:
        payload = {"ok": False, "error": "invalid_runtime_response"}
    payload.update({"project_id": project_id, "service": service})
    main._audit("laravel.admin_access_status", {"project_id": project_id, "email": email, "service": service}, {"ok": payload.get("ok"), "role": payload.get("role"), "is_active": payload.get("is_active")})
    return payload


def admin_access_repair(project_id: str, email: str, service: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    email = str(email or "").strip().lower()
    resolved, repository, container = _resolve_laravel_container(project_id, service)
    if not resolved.get("ok"):
        return resolved
    if not email or "@" not in email or len(email) > 254:
        return {"ok": False, "error": "invalid_email", "project_id": project_id}
    code = r'''
require "/var/www/html/vendor/autoload.php";
$app = require "/var/www/html/bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$u = App\Models\User::where("email", getenv("VITRINE_ADMIN_EMAIL"))->first();
if (!$u) { echo json_encode(["ok"=>false,"error"=>"user_not_found"]); exit(2); }
$u->role = "admin";
$u->status = "active";
if (Illuminate\Support\Facades\Schema::hasColumn("users", "is_active")) { $u->is_active = true; }
$u->save();
echo json_encode(["ok"=>true,"result"=>"repaired","email"=>$u->email,"role"=>$u->role,"status"=>$u->status,"is_active"=>(bool)($u->is_active ?? false)]);
'''
    result = main._run(
        ["docker", "exec", "-e", f"VITRINE_ADMIN_EMAIL={email}", str(container), "php", "-r", code],
        repository,
        timeout=30,
    )
    try:
        payload = main.json.loads(str(result.get("stdout", "")).strip() or "{}")
    except main.json.JSONDecodeError:
        payload = {"ok": False, "error": "invalid_runtime_response"}
    payload.update({"project_id": project_id, "service": service})
    main._audit("laravel.admin_access_repair", {"project_id": project_id, "email": email, "service": service}, {"ok": payload.get("ok"), "status": payload.get("status")})
    return payload


def admin_access_reset(project_id: str, email: str, new_password: str, service: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    email = str(email or "").strip().lower()
    password = str(new_password or "")
    if not email or "@" not in email or len(email) > 254:
        return {"ok": False, "error": "invalid_email", "project_id": project_id}
    if len(password) < 12 or len(password) > 200:
        return {"ok": False, "error": "password_policy_failed", "minimum_length": 12, "maximum_length": 200}
    resolved, repository, container = _resolve_laravel_container(project_id, service)
    if not resolved.get("ok"):
        return resolved
    code = r'''
require "/var/www/html/vendor/autoload.php";
$app = require "/var/www/html/bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$u = App\Models\User::where("email", getenv("VITRINE_ADMIN_EMAIL"))->first();
if (!$u) { echo json_encode(["ok"=>false,"error"=>"user_not_found"]); exit(2); }
$password = stream_get_contents(STDIN);
if (strlen($password) < 12) { echo json_encode(["ok"=>false,"error"=>"password_policy_failed"]); exit(3); }
$u->role = "admin";
$u->status = "active";
if (Illuminate\Support\Facades\Schema::hasColumn("users", "is_active")) { $u->is_active = true; }
$u->password = Illuminate\Support\Facades\Hash::make($password);
$u->save();
echo json_encode(["ok"=>true,"status"=>"reset","email"=>$u->email,"role"=>$u->role,"is_active"=>(bool)$u->is_active]);
'''
    result = main._run(
        ["docker", "exec", "-i", "-e", f"VITRINE_ADMIN_EMAIL={email}", str(container), "php", "-r", code],
        repository,
        timeout=30,
        input_text=password,
    )
    try:
        payload = main.json.loads(str(result.get("stdout", "")).strip() or "{}")
    except main.json.JSONDecodeError:
        payload = {"ok": False, "error": "invalid_runtime_response"}
    payload.update({"project_id": project_id, "service": service})
    main._audit("laravel.admin_access_reset", {"project_id": project_id, "email": email, "service": service}, {"ok": payload.get("ok"), "status": payload.get("status")})
    return payload


def migrate_paths(project_id: str, service: str, paths: list[str], confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    resolved, repository, container = _resolve_laravel_container(project_id, service)
    if not resolved.get("ok"):
        return resolved
    safe_paths: list[str] = []
    for raw in paths or []:
        path = str(raw or "").strip().replace("\\", "/")
        if not path.startswith("database/migrations/") or ".." in path.split("/") or not path.endswith(".php"):
            return {"ok": False, "error": "migration_path_invalid", "path": path}
        target = (repository / path).resolve()
        try:
            target.relative_to(repository.resolve())
        except ValueError:
            return {"ok": False, "error": "migration_path_outside_repository", "path": path}
        if not target.is_file():
            return {"ok": False, "error": "migration_path_not_found", "path": path}
        safe_paths.append(path)
    if not safe_paths:
        return {"ok": False, "error": "migration_paths_required"}

    args = ["docker", "exec", str(container), "php", "artisan", "migrate", "--force", "--no-ansi"]
    for path in safe_paths:
        args.append(f"--path={path}")
    result = main._run(args, repository, timeout=300)
    result.update({"project_id": project_id, "service": service, "paths": safe_paths})
    main._audit("laravel.migrate_paths", {"project_id": project_id, "service": service, "paths": safe_paths}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result

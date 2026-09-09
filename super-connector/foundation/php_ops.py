from __future__ import annotations

import hashlib
import re
from typing import Any

import main
from foundation import runtime_ops

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_ALLOWED_ASPECTS = {"9:16", "16:9"}
_ALLOWED_DURATIONS = {4, 6, 8}
_ALLOWED_RESOLUTIONS = {"720p", "1080p", "4k"}


def _dependency_image(project_id: str, repository) -> tuple[str, dict[str, Any] | None]:
    if not (repository / "composer.lock").is_file():
        return "", {"ok": False, "error": "composer_lock_required"}
    if not main.PHP_RUNNER_IMAGE:
        return "", {"ok": False, "error": "php_runner_image_unavailable"}
    lock_hash = hashlib.sha256((repository / "composer.lock").read_bytes()).hexdigest()[:12]
    project_tag = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:8]
    image = f"vitrine-super-laravel-test:{project_tag}-{lock_hash}"
    check = main._run(["docker", "image", "inspect", image], repository, timeout=30)
    if not check.get("ok"):
        return "", {"ok": False, "error": "php_dependency_image_unavailable", "runtime_image": image}
    return image, None


def video_producer_validate(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    entrypoint = repository / "bin" / "veo-generate.php"
    if not entrypoint.is_file():
        return {"ok": False, "error": "veo_entrypoint_missing"}
    image, error = _dependency_image(project_id, repository)
    if error:
        return error
    syntax = main._run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--mount", f"type=bind,src={repository},dst=/source,readonly", "--entrypoint", "php", image, "-l", "/source/bin/veo-generate.php"],
        repository,
        timeout=60,
    )
    result = {"ok": bool(syntax.get("ok")), "project_id": project_id, "entrypoint": "bin/veo-generate.php", "syntax": syntax.get("stdout", "").strip(), "network": "none", "generation_executed": False}
    main._audit("php.video_producer_validate", {"project_id": project_id}, {"ok": result["ok"], "generation_executed": False})
    return result


def video_producer_generate(project_id: str, request_id: str, title: str, prompt: str, aspect_ratio: str = "9:16", duration: int = 8, resolution: str = "720p", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if not _SAFE_ID.fullmatch(str(request_id or "")):
        return {"ok": False, "error": "invalid_request_id"}
    title = str(title or "").strip()
    prompt = str(prompt or "").strip()
    resolution = str(resolution or "").lower()
    if not title or len(title) > 180:
        return {"ok": False, "error": "invalid_title"}
    if not prompt or len(prompt) > 8000:
        return {"ok": False, "error": "invalid_prompt"}
    if aspect_ratio not in _ALLOWED_ASPECTS or int(duration) not in _ALLOWED_DURATIONS or resolution not in _ALLOWED_RESOLUTIONS:
        return {"ok": False, "error": "invalid_video_parameters"}
    if resolution in {"1080p", "4k"} and int(duration) != 8:
        return {"ok": False, "error": "high_resolution_requires_8_seconds"}

    project = main._load_project(project_id)
    repository = main._repository(project)
    if not (repository / "bin" / "veo-generate.php").is_file():
        return {"ok": False, "error": "veo_entrypoint_missing"}
    try:
        secret = runtime_ops._read_secret(project, "GEMINI_API_KEY")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    image, error = _dependency_image(project_id, repository)
    if error:
        return error

    command = [
        "docker", "run", "--rm", "--network", "bridge", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "768m", "--cpus", "1",
        "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=64m", "--env", "GEMINI_API_KEY", "--mount", f"type=bind,src={repository},dst=/source,readonly", "--workdir", "/source", "--entrypoint", "php", image,
        "bin/veo-generate.php", "--request-id", request_id, "--title", title, "--prompt", prompt, "--aspect-ratio", aspect_ratio, "--duration", str(int(duration)), "--resolution", resolution, "--provider", "gemini_veo",
    ]
    result = main._run(command, repository, timeout=900, env={"GEMINI_API_KEY": secret})
    safe = {"ok": result.get("ok", False), "exit_code": result.get("exit_code"), "stdout": result.get("stdout", "")[-12000:], "stderr": result.get("stderr", "")[-4000:], "project_id": project_id, "request_id": request_id, "provider": "gemini_veo", "auto_regenerate": False, "auto_publish": False}
    main._audit("php.video_producer_generate", {"project_id": project_id, "request_id": request_id, "aspect_ratio": aspect_ratio, "duration": int(duration), "resolution": resolution}, {"ok": safe["ok"], "exit_code": safe["exit_code"]})
    return safe

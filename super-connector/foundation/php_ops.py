from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main
from foundation import runtime_ops

_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_ALLOWED_ASPECTS = {"9:16", "16:9"}
_ALLOWED_DURATIONS = {4, 6, 8}
_ALLOWED_RESOLUTIONS = {"720p", "1080p", "4k"}


def _safe_project_file(project_id: str, path: str) -> tuple[Path, Path]:
    project = main._load_project(project_id)
    repository = main._repository(project).resolve()
    relative = Path(str(path or "").strip())
    if not str(relative) or relative.is_absolute():
        raise ValueError("invalid_relative_path")
    target = (repository / relative).resolve()
    try:
        target.relative_to(repository)
    except ValueError as exc:
        raise PermissionError("path_outside_repository") from exc
    if not target.is_file():
        raise FileNotFoundError("file_not_found")
    return repository, target


def php_lint(project_id: str, path: str) -> dict[str, Any]:
    try:
        repository, target = _safe_project_file(project_id, path)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id, "path": path}
    if target.suffix.lower() != ".php":
        return {"ok": False, "error": "php_file_required", "project_id": project_id, "path": path}
    if not main.PHP_RUNNER_IMAGE:
        return {"ok": False, "error": "php_runner_image_unavailable", "project_id": project_id, "path": path}

    relative = target.relative_to(repository)
    result = main._run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,src={repository},dst=/source,readonly",
            "--entrypoint", "php", main.PHP_RUNNER_IMAGE, "-l", f"/source/{relative.as_posix()}",
        ],
        repository,
        timeout=60,
    )
    safe = {
        "ok": bool(result.get("ok")),
        "project_id": project_id,
        "path": relative.as_posix(),
        "exit_code": result.get("exit_code"),
        "stdout": result.get("stdout", "")[-4000:],
        "stderr": result.get("stderr", "")[-2000:],
        "network": "none",
        "read_only": True,
    }
    main._audit("php.lint", {"project_id": project_id, "path": relative.as_posix()}, {"ok": safe["ok"], "exit_code": safe["exit_code"]})
    return safe


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



def video_producer_download(project_id: str, request_id: str, version_id: str, video_url: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if project_id != "vitrine-marketing-agents-core-hml":
        return {"ok": False, "error": "project_not_allowed"}
    if not _SAFE_ID.fullmatch(str(request_id or "")) or not _SAFE_ID.fullmatch(str(version_id or "")):
        return {"ok": False, "error": "invalid_video_identifier"}

    parsed = urllib.parse.urlparse(str(video_url or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "generativelanguage.googleapis.com":
        return {"ok": False, "error": "video_url_not_allowed"}
    if not re.fullmatch(r"/v1beta/files/[A-Za-z0-9._:-]+:download", parsed.path):
        return {"ok": False, "error": "video_url_path_not_allowed"}
    if parsed.query != "alt=media":
        return {"ok": False, "error": "video_url_query_not_allowed"}

    project = main._load_project(project_id)
    repository = main._repository(project).resolve()
    workspace = repository.parent
    folder_name = "reel-01-vitrine-social-midia" if request_id == "REEL-01-VITRINE-SOCIAL-MIDIA-20260911" else request_id.lower()
    output_dir = (workspace / "storage" / "app" / "marketing" / "video-producer" / folder_name).resolve()
    allowed_root = (workspace / "storage" / "app" / "marketing" / "video-producer").resolve()
    try:
        output_dir.relative_to(allowed_root)
    except ValueError:
        return {"ok": False, "error": "output_path_not_allowed"}

    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o750)
    target = output_dir / f"{version_id}.mp4"
    manifest = output_dir / f"{version_id}.json"
    checksum_file = output_dir / f"{version_id}.sha256"

    if target.is_file() and target.stat().st_size > 1024:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "ok": True,
            "status": "already_preserved",
            "project_id": project_id,
            "request_id": request_id,
            "version_id": version_id,
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": digest,
            "auto_publish": False,
            "regeneration_executed": False,
        }

    try:
        secret = runtime_ops._read_secret(project, "GEMINI_API_KEY")
    except (FileNotFoundError, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}

    temporary = output_dir / f".{version_id}.mp4.part"
    maximum_bytes = 100 * 1024 * 1024
    size = 0
    digest = hashlib.sha256()
    request = urllib.request.Request(
        video_url,
        headers={
            "x-goog-api-key": secret,
            "Accept": "video/mp4,application/octet-stream",
            "User-Agent": "Vitrine-Super-Video-Preserver/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as handle:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "video" not in content_type and "octet-stream" not in content_type:
                raise ValueError("unexpected_content_type")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("video_exceeds_100mb_limit")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        temporary.unlink(missing_ok=True)
        safe_error = exc.code if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        result = {"ok": False, "error": "video_download_failed", "detail": str(safe_error)}
        main._audit("php.video_producer_download", {"project_id": project_id, "request_id": request_id, "version_id": version_id}, result)
        return result
    finally:
        secret = ""

    if size <= 1024:
        temporary.unlink(missing_ok=True)
        return {"ok": False, "error": "downloaded_video_too_small"}
    with temporary.open("rb") as handle:
        header = handle.read(32)
    if b"ftyp" not in header:
        temporary.unlink(missing_ok=True)
        return {"ok": False, "error": "downloaded_file_is_not_mp4"}

    image = "vitrine-marketing-agents-core-hml-app:latest"
    image_check = main._run(["docker", "image", "inspect", image], repository, timeout=30)
    if not image_check.get("ok"):
        temporary.unlink(missing_ok=True)
        return {"ok": False, "error": "video_probe_image_unavailable", "runtime_image": image}
    probe = main._run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,src={output_dir},dst=/media,readonly",
            "--entrypoint", "ffprobe", image,
            "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height",
            "-of", "json", f"/media/{temporary.name}",
        ],
        repository,
        timeout=60,
    )
    if not probe.get("ok"):
        temporary.unlink(missing_ok=True)
        return {"ok": False, "error": "ffprobe_validation_failed", "stderr": probe.get("stderr", "")[-1000:]}

    os.replace(temporary, target)
    os.chmod(target, 0o640)
    sha256 = digest.hexdigest()
    checksum_file.write_text(f"{sha256}  {target.name}\n", encoding="utf-8")
    os.chmod(checksum_file, 0o640)
    record = {
        "request_id": request_id,
        "version_id": version_id,
        "provider": "gemini_veo",
        "preserved_at": datetime.now(timezone.utc).isoformat(),
        "path": str(target),
        "bytes": size,
        "sha256": sha256,
        "probe": json.loads(probe.get("stdout") or "{}"),
        "auto_publish": False,
        "regeneration_executed": False,
    }
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest, 0o640)

    result = {"ok": True, "status": "preserved", "project_id": project_id, **record}
    main._audit(
        "php.video_producer_download",
        {"project_id": project_id, "request_id": request_id, "version_id": version_id},
        {"ok": True, "path": str(target), "bytes": size, "sha256": sha256},
    )
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

    bootstrap = (
        "set -eu; "
        "umask 077; "
        "mkdir -p /work/project; "
        "cp -R /var/www/html/. /work/project/; "
        "find /source -mindepth 1 -maxdepth 1 ! -name .git -exec cp -R {} /work/project/ \\;; "
        "cd /work/project; "
        "mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views bootstrap/cache; "
        "chmod -R u+rwX storage bootstrap/cache; "
        "test -f vendor/autoload.php; "
        "exec php bin/veo-generate.php \"$@\""
    )

    command = [
        "docker", "run", "--rm", "--network", "bridge", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "768m", "--cpus", "1",
        "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=64m", "--tmpfs", "/work:rw,nosuid,nodev,mode=1777,size=1024m", "--env", "GEMINI_API_KEY",
        "--mount", f"type=bind,src={repository},dst=/source,readonly", "--entrypoint", "sh", image, "-lc", bootstrap, "sh",
        "--request-id", request_id, "--title", title, "--prompt", prompt, "--aspect-ratio", aspect_ratio, "--duration", str(int(duration)), "--resolution", resolution, "--provider=gemini_veo",
    ]
    result = main._run(command, repository, timeout=900, env={"GEMINI_API_KEY": secret})
    safe = {"ok": result.get("ok", False), "exit_code": result.get("exit_code"), "stdout": result.get("stdout", "")[-12000:], "stderr": result.get("stderr", "")[-4000:], "project_id": project_id, "request_id": request_id, "provider": "gemini_veo", "auto_regenerate": False, "auto_publish": False}
    main._audit("php.video_producer_generate", {"project_id": project_id, "request_id": request_id, "aspect_ratio": aspect_ratio, "duration": int(duration), "resolution": resolution}, {"ok": safe["ok"], "exit_code": safe["exit_code"]})
    return safe

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import foundation_entrypoint  # noqa: F401 - registers the existing tool catalog
import main
from foundation import php_ops

_ORIGINAL_VIDEO_DOWNLOAD = php_ops.video_producer_download
_MARKETING_PROJECT_ID = "vitrine-marketing-agents-core-hml"
_MARKETING_IMAGE = "vitrine-marketing-agents-core-hml-app:latest"
_LOGO_PATH = Path("assets/img/logo-vitrine-ai-pro.png")


def _brand_preserved_video(project_id: str, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return result
    if project_id != _MARKETING_PROJECT_ID:
        return result

    raw_path = Path(str(result.get("path") or "")).resolve()
    if not raw_path.is_file() or raw_path.suffix.lower() != ".mp4":
        return {**result, "ok": False, "error": "preserved_video_missing_for_branding"}

    project = main._load_project(project_id)
    repository = main._repository(project).resolve()
    workspace = repository.parent.resolve()
    allowed_root = (workspace / "storage" / "app" / "marketing" / "video-producer").resolve()
    try:
        raw_path.relative_to(allowed_root)
    except ValueError:
        return {**result, "ok": False, "error": "branding_source_path_not_allowed"}

    logo_path = (repository / _LOGO_PATH).resolve()
    try:
        logo_path.relative_to(repository)
    except ValueError:
        return {**result, "ok": False, "error": "branding_logo_path_not_allowed"}
    if not logo_path.is_file():
        return {**result, "ok": False, "error": "branding_logo_missing", "logo": str(_LOGO_PATH)}

    output_dir = raw_path.parent.resolve()
    os.chmod(output_dir, 0o755)
    os.chmod(raw_path, 0o644)

    branded_path = raw_path.with_name(f"{raw_path.stem}-branded.mp4")
    branded_manifest = branded_path.with_suffix(".json")
    branded_checksum = branded_path.with_suffix(".sha256")

    if branded_path.is_file() and branded_path.stat().st_size > 1024:
        os.chmod(branded_path, 0o644)
        branded_sha256 = hashlib.sha256(branded_path.read_bytes()).hexdigest()
        return {
            **result,
            "status": "already_branded",
            "raw_path": str(raw_path),
            "raw_sha256": result.get("sha256"),
            "path": str(branded_path),
            "branded_path": str(branded_path),
            "bytes": branded_path.stat().st_size,
            "sha256": branded_sha256,
            "branded": True,
            "branding_logo": str(_LOGO_PATH),
            "auto_publish": False,
        }

    image_check = main._run(["docker", "image", "inspect", _MARKETING_IMAGE], repository, timeout=30)
    if not image_check.get("ok"):
        return {**result, "ok": False, "error": "branding_runtime_image_unavailable", "runtime_image": _MARKETING_IMAGE}

    probe = main._run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,src={output_dir},dst=/media,readonly",
            "--entrypoint", "ffprobe", _MARKETING_IMAGE,
            "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
            "-of", "json", f"/media/{raw_path.name}",
        ],
        repository,
        timeout=60,
    )
    if not probe.get("ok"):
        return {**result, "ok": False, "error": "branding_ffprobe_failed", "stderr": probe.get("stderr", "")[-1000:]}

    try:
        probe_json = json.loads(probe.get("stdout") or "{}")
        stream = (probe_json.get("streams") or [])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        return {**result, "ok": False, "error": "branding_video_dimensions_unavailable"}
    if width < 100 or height < 100:
        return {**result, "ok": False, "error": "branding_video_dimensions_invalid"}

    logo_width = max(72, round(width * 0.18))
    margin = max(24, round(width * 0.044))
    temporary = output_dir / f".{branded_path.name}.part.mp4"
    filter_graph = (
        f"[1:v]scale={logo_width}:-1:flags=lanczos,format=rgba,"
        "colorchannelmixer=aa=0.95[logo];"
        f"[0:v][logo]overlay=W-w-{margin}:{margin}:format=auto[v]"
    )

    encode = main._run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "1024m", "--cpus", "2",
            "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=128m",
            "--mount", f"type=bind,src={output_dir},dst=/media",
            "--mount", f"type=bind,src={repository},dst=/source,readonly",
            "--entrypoint", "ffmpeg", _MARKETING_IMAGE,
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", f"/media/{raw_path.name}",
            "-i", f"/source/{_LOGO_PATH.as_posix()}",
            "-filter_complex", filter_graph,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            f"/media/{temporary.name}",
        ],
        repository,
        timeout=600,
    )
    if not encode.get("ok"):
        temporary.unlink(missing_ok=True)
        return {**result, "ok": False, "error": "video_branding_failed", "stderr": encode.get("stderr", "")[-2000:]}
    if not temporary.is_file() or temporary.stat().st_size <= 1024:
        temporary.unlink(missing_ok=True)
        return {**result, "ok": False, "error": "branded_video_invalid"}

    os.replace(temporary, branded_path)
    os.chmod(branded_path, 0o644)
    branded_sha256 = hashlib.sha256(branded_path.read_bytes()).hexdigest()
    branded_checksum.write_text(f"{branded_sha256}  {branded_path.name}\n", encoding="utf-8")
    os.chmod(branded_checksum, 0o640)

    brand_record = {
        "request_id": result.get("request_id"),
        "version_id": result.get("version_id"),
        "branded_at": datetime.now(timezone.utc).isoformat(),
        "raw_path": str(raw_path),
        "raw_sha256": result.get("sha256"),
        "path": str(branded_path),
        "sha256": branded_sha256,
        "bytes": branded_path.stat().st_size,
        "logo": str(_LOGO_PATH),
        "logo_width_px": logo_width,
        "margin_px": margin,
        "opacity": 0.95,
        "position": "top-right",
        "auto_publish": False,
    }
    branded_manifest.write_text(json.dumps(brand_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(branded_manifest, 0o640)

    branded_result = {
        **result,
        "status": "branded",
        "raw_path": str(raw_path),
        "raw_sha256": result.get("sha256"),
        "path": str(branded_path),
        "branded_path": str(branded_path),
        "bytes": branded_path.stat().st_size,
        "sha256": branded_sha256,
        "branded": True,
        "branding_logo": str(_LOGO_PATH),
        "branding_position": "top-right",
        "auto_publish": False,
    }
    main._audit(
        "php.video_producer_brand",
        {"project_id": project_id, "request_id": result.get("request_id"), "version_id": result.get("version_id")},
        {"ok": True, "raw_path": str(raw_path), "branded_path": str(branded_path), "sha256": branded_sha256},
    )
    return branded_result


def _video_producer_download_with_branding(
    project_id: str,
    request_id: str,
    version_id: str,
    video_url: str,
    confirm: str = "",
) -> dict[str, Any]:
    result = _ORIGINAL_VIDEO_DOWNLOAD(project_id, request_id, version_id, video_url, confirm)
    return _brand_preserved_video(project_id, result)


def _video_producer_brand(
    project_id: str,
    request_id: str,
    version_id: str,
    confirm: str = "",
) -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if project_id != _MARKETING_PROJECT_ID:
        return {"ok": False, "error": "branding_project_not_allowed", "project_id": project_id}

    project = main._load_project(project_id)
    repository = main._repository(project).resolve()
    workspace = repository.parent.resolve()
    folder_name = "reel-01-vitrine-social-midia" if request_id == "REEL-01-VITRINE-SOCIAL-MIDIA-20260911" else request_id.lower()
    output_dir = (workspace / "storage" / "app" / "marketing" / "video-producer" / folder_name).resolve()
    raw_path = (output_dir / f"{version_id}.mp4").resolve()
    try:
        raw_path.relative_to(output_dir)
    except ValueError:
        return {"ok": False, "error": "branding_source_path_not_allowed"}
    if not raw_path.is_file():
        return {"ok": False, "error": "preserved_video_missing_for_branding", "path": str(raw_path)}

    raw_sha256 = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    result = {
        "ok": True,
        "status": "preserved",
        "project_id": project_id,
        "request_id": request_id,
        "version_id": version_id,
        "path": str(raw_path),
        "bytes": raw_path.stat().st_size,
        "sha256": raw_sha256,
        "auto_publish": False,
    }
    return _brand_preserved_video(project_id, result)


php_ops.video_producer_download = _video_producer_download_with_branding
main.mcp.tool()(_video_producer_brand)
main.VERSION = "0.3.14-secret-broker"


if __name__ == "__main__":
    main.mcp.run(transport="http", host="0.0.0.0", port=8000)

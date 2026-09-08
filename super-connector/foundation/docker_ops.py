from __future__ import annotations

import json
from typing import Any

import main


def docker_status() -> dict[str, Any]:
    result = main._run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        main.Path("/"),
        timeout=60,
    )
    containers: list[dict[str, Any]] = []
    if result.get("ok"):
        for line in str(result.get("stdout", "")).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                containers.append({"raw": line})
    return {
        "ok": result.get("ok", False),
        "exit_code": result.get("exit_code"),
        "containers": containers,
        "stderr": result.get("stderr", ""),
    }


def image_inspect(image: str) -> dict[str, Any]:
    value = str(image or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-"
    if not value or any(ch not in allowed for ch in value):
        return {"ok": False, "error": "invalid_image_reference"}
    result = main._run(["docker", "image", "inspect", value], main.Path("/"), timeout=60)
    parsed: Any = None
    if result.get("ok"):
        try:
            parsed = json.loads(str(result.get("stdout", "")))
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": result.get("ok", False),
        "image": value,
        "inspect": parsed,
        "exit_code": result.get("exit_code"),
        "stderr": result.get("stderr", ""),
    }


def container_inspect(container: str) -> dict[str, Any]:
    value = str(container or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not value or any(ch not in allowed for ch in value):
        return {"ok": False, "error": "invalid_container_name"}
    result = main._run(["docker", "inspect", value], main.Path("/"), timeout=60)
    parsed: Any = None
    if result.get("ok"):
        try:
            parsed = json.loads(str(result.get("stdout", "")))
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": result.get("ok", False),
        "container": value,
        "inspect": parsed,
        "exit_code": result.get("exit_code"),
        "stderr": result.get("stderr", ""),
    }


def container_health(container: str) -> dict[str, Any]:
    inspected = container_inspect(container)
    if not inspected.get("ok"):
        return inspected
    items = inspected.get("inspect") or []
    state: dict[str, Any] = items[0].get("State", {}) if items else {}
    health = state.get("Health", {}) or {}
    return {
        "ok": True,
        "container": container,
        "status": state.get("Status"),
        "running": state.get("Running"),
        "health": health.get("Status"),
        "exit_code": state.get("ExitCode"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
    }


def container_logs(container: str, tail: int = 200) -> dict[str, Any]:
    value = str(container or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not value or any(ch not in allowed for ch in value):
        return {"ok": False, "error": "invalid_container_name"}
    safe_tail = max(1, min(int(tail), 1000))
    result = main._run(["docker", "logs", "--tail", str(safe_tail), value], main.Path("/"), timeout=60)
    return {**result, "container": value, "tail": safe_tail}

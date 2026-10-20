"""Read-only TV Sumare HeyGen inventory. Never loads application PHP or env."""
from __future__ import annotations

import json
import subprocess

CONTAINERS = {"production": "tvsumare_web_prod", "homologation": "tvsumare_web"}
PHP_SCAN = r'''
// php -n disables shared extensions. Load only the standard tokenizer, never app ini.
if (!function_exists('token_get_all')) { @dl('tokenizer.so'); }
if (!function_exists('token_get_all')) { exit(2); }
$paths = ['includes/heygen_helper.php', 'includes/video_ai_helper.php',
          'admin/reporter-ia.php', 'reporter-ia.php',
          'admin/heygen-diagnostico.php', 'admin/status.php', 'status.php'];
$rows = [];
foreach ($paths as $path) {
    $file = '/var/www/html/'.$path;
    if (is_link($file) || !is_file($file) || filesize($file) > 1048576) {
        $rows[] = ['path'=>$path, 'error'=>'missing_or_unsafe']; continue;
    }
    $source = file_get_contents($file);
    if ($source === false) { $rows[] = ['path'=>$path, 'error'=>'unreadable']; continue; }
    $endpoints = [];
    foreach (token_get_all($source) as $token) {
        if (!is_array($token) || $token[0] !== T_CONSTANT_ENCAPSED_STRING) continue;
        // Return only known endpoint names, never strings, IDs, query values or source.
        foreach (['/v1/video_status.get', '/v2/video/generate', '/v3/video-agents',
                  '/v3/videos', '/v1/voice.list', '/v2/voices', '/v3/voices',
                  '/v1/avatar.list', '/v2/avatars', '/v3/avatars',
                  '/v1/user/me', '/v2/user/remaining_quota', '/v3/users/me'] as $endpoint) {
            if (strpos($token[1], $endpoint) !== false) $endpoints[$endpoint] = true;
        }
    }
    $rows[] = ['path'=>$path, 'sha256'=>hash('sha256', $source),
               'endpoint_literals'=>array_keys($endpoints)];
}
echo json_encode(['files'=>$rows], JSON_UNESCAPED_SLASHES);
'''


def inventory(environment: str) -> dict:
    if environment not in CONTAINERS:
        return {"ok": False, "error": "environment_not_allowed"}
    container = CONTAINERS[environment]
    commands = [
        ["docker", "inspect", "--format", "{{.Id}} {{.Image}} {{.State.Running}}", container],
        ["docker", "exec", container, "php", "-n", "-r", PHP_SCAN],
    ]
    results = []
    try:
        for command in commands:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                  check=False, env={"PATH": "/usr/local/bin:/usr/bin:/bin"})
            if proc.returncode:
                # Docker/PHP stderr may contain unexpected data; never forward it.
                return {"ok": False, "error": "runtime_inventory_failed",
                        "stage": len(results), "exit_code": proc.returncode}
            if len(proc.stdout) > 32768:
                return {"ok": False, "error": "inventory_response_too_large"}
            results.append(proc.stdout)
        container_id, image_id, running = results[0].strip().split()
        import re
        if not re.fullmatch(r"[a-f0-9]{64}", container_id) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise ValueError("invalid_identity")
        body = json.loads(results[1])
        files = body["files"]
        if not isinstance(files, list) or len(files) != 7:
            raise ValueError("invalid_files")
        # Project a strict result schema even if the container's response changes.
        safe = []
        allowed_paths = {"includes/heygen_helper.php", "includes/video_ai_helper.php",
                         "admin/reporter-ia.php", "reporter-ia.php",
                         "admin/heygen-diagnostico.php", "admin/status.php", "status.php"}
        seen = set()
        for row in files:
            path = row["path"]
            if path not in allowed_paths or path in seen:
                raise ValueError("invalid_path")
            seen.add(path)
            if "error" in row:
                safe.append({"path": path, "error": "file_unavailable"})
                continue
            digest = row["sha256"]
            endpoints = row["endpoint_literals"]
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or not isinstance(endpoints, list):
                raise ValueError("invalid_digest")
            allowed_endpoints = set(re.findall(r"'(/v[123]/[^']+)'", PHP_SCAN))
            if any(not isinstance(e, str) or e not in allowed_endpoints for e in endpoints):
                raise ValueError("invalid_endpoint")
            safe.append({"path": path, "sha256": digest, "endpoint_literals": endpoints})
        complete = all("error" not in row for row in safe)
        return {"ok": complete, "environment": environment, "container": container,
                "container_id": container_id, "image_id": image_id,
                "running": running == "true", "files": safe,
                "scope": "known_entrypoints_only", "paid_requests": 0}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return {"ok": False, "error": "invalid_or_unavailable_runtime_inventory"}

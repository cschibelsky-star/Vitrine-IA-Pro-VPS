from __future__ import annotations

import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
TARGET = ROOT / 'project_manager_operations.py'
COMPOSE = ['docker', 'compose', '-f', 'docker-compose.mcp.yml', '-f', 'docker-compose.connector-v2.override.yml']

MODEL_BLOCK = '''\n\nclass ProjectReadRequest(BaseModel):\n    project_id: str\n    path: str\n    start_line: int = 1\n    end_line: int = 400\n'''

ROUTE_BLOCK = '''\n\n@router.post("/read-file", dependencies=[Depends(auth)])\ndef project_read_file(req: ProjectReadRequest) -> dict[str, Any]:\n    try:\n        manifest = load_manifest(req.project_id)\n        relative, target, _ = safe_project_file(manifest, req.path, must_exist=True)\n        start_line = max(1, int(req.start_line))\n        end_line = max(start_line, min(int(req.end_line), start_line + 1999))\n        text = target.read_text(encoding="utf-8")\n        lines = text.splitlines()\n        selected = lines[start_line - 1:end_line]\n        result = {\n            "ok": True,\n            "project_id": req.project_id,\n            "path": relative,\n            "start_line": start_line,\n            "end_line": min(end_line, len(lines)),\n            "total_lines": len(lines),\n            "content": "\\n".join(selected),\n        }\n        audit("project_read_file", req.project_id, {"path": relative, "start_line": start_line, "end_line": end_line}, {"ok": True, "path": relative, "lines": len(selected)})\n        return result\n    except UnicodeDecodeError as exc:\n        raise HTTPException(status_code=403, detail="non_text_path_blocked") from exc\n    except HTTPException as exc:\n        _safe_audit_failure("project_read_file", req.project_id, req.path, exc)\n        raise\n    except OSError as exc:\n        audit("project_read_file", req.project_id, {"path": req.path}, {"ok": False, "detail": type(exc).__name__})\n        raise HTTPException(status_code=500, detail="project_read_failed") from exc\n'''


def run(command: list[str], cwd: Path = ROOT) -> None:
    proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f'command failed ({proc.returncode}): {" ".join(command)}')


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f'target_not_found:{TARGET}')

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = TARGET.with_name(f'{TARGET.name}.backup-read-file-{stamp}')
    shutil.copy2(TARGET, backup)
    print(f'BACKUP={backup}')

    text = TARGET.read_text(encoding='utf-8')
    changed = False

    if 'class ProjectReadRequest(BaseModel):' not in text:
        marker = '\n\nclass ProjectPathRequest(BaseModel):\n'
        if marker not in text:
            raise RuntimeError('model_anchor_not_found')
        text = text.replace(marker, MODEL_BLOCK + marker, 1)
        changed = True

    if '@router.post("/read-file"' not in text:
        marker = '\n\n@router.post("/write-file", dependencies=[Depends(auth)])\n'
        if marker not in text:
            raise RuntimeError('route_anchor_not_found')
        text = text.replace(marker, ROUTE_BLOCK + marker, 1)
        changed = True

    if changed:
        TARGET.write_text(text, encoding='utf-8')

    run([sys.executable, '-m', 'py_compile', str(TARGET)])
    run(COMPOSE + ['config', '--quiet'])
    run(COMPOSE + ['build', '--no-cache', 'ops_broker'])
    run(COMPOSE + ['up', '-d', 'ops_broker', 'vps_mcp_connector'])

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        proc = subprocess.run(
            ['docker', 'inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', 'vitrine_mcp_ops_broker'],
            text=True, capture_output=True, check=False,
        )
        status = proc.stdout.strip().lower()
        if status == 'healthy':
            print('OPS_BROKER_HEALTH=PASS')
            print('PROJECT_READ_FILE_ROUTE_HOTFIX=SIM')
            return 0
        if status in {'dead', 'exited'}:
            break
        time.sleep(2)

    raise RuntimeError('ops_broker_not_healthy')


if __name__ == '__main__':
    raise SystemExit(main())

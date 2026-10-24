"""Fixed, read-only Docker volume snapshot runner for Assessor HML."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

DB_VOLUME = "assessor-online-trial-hml_assessor_private"
STORAGE_VOLUME = "assessor-online-trial-hml_assessor_storage"
IMAGE = "python:3.12-alpine"


def snapshot(backup_id: str, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("assessor_sqlite_backup.py").read_text()
    script += (
        "\nif __name__ == '__main__':\n"
        " from pathlib import Path\n"
        " import json\n"
        " result = create_backup(Path('/source-db/database.sqlite'), "
        "Path('/source-storage'), Path('/backups') / " + repr(backup_id) + ")\n"
        " print(json.dumps(result))\n"
    )
    cmd = [
        "docker", "run", "--rm", "-i", "--network", "none",
        "--read-only", "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL", "--pids-limit", "128", "--memory", "256m",
        "--mount", f"type=volume,source={DB_VOLUME},target=/source-db,readonly,volume-nocopy",
        "--mount", f"type=volume,source={STORAGE_VOLUME},target=/source-storage,readonly,volume-nocopy",
        "--mount", f"type=bind,source={root},target=/backups",
        IMAGE, "python", "-"
    ]
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True, timeout=240)
    if proc.returncode:
        return {"ok": False, "error": "isolated_snapshot_failed", "exit_code": proc.returncode}
    return json.loads(proc.stdout.strip().splitlines()[-1])

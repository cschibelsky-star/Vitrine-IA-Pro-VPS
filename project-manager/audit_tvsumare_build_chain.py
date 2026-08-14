from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path('/srv/tvsumare/repository')
DEFAULT_IMAGE = 'repository-web'


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def pick_image() -> str:
    inspect = run(['docker', 'inspect', '-
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/tvsumare/repository/admin')
BOLETIM = ROOT / 'boletim-ia.php'
REPORTER = ROOT / 'reporter-ia.php'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f'{label}=ALREADY_APPLIED')
            return text
        raise RuntimeError(f'{label}:anchor_not_found')
    if count != 1:
        raise RuntimeError(f'{label}:anchor
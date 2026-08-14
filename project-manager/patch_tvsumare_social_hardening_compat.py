from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path('/srv/tvsumare/repository/docker/apply-social-distribution-hardening.php')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

REPLACEMENTS = [
    (
        "\"if(\\$selected && ds_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption
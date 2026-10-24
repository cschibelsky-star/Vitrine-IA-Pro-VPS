#!/usr/bin/env python3
"""Offline fail-closed tests for Assessor volume helper; never invokes Docker."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import tempfile

path = Path(__file__).with_name("assessor_sqlite_volume_helper.py")
spec = importlib.util.spec_from_file_location("assessor_sqlite_volume_helper", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    with patch.object(module.subprocess, "run", side_effect=AssertionError("Docker called")):
        assert module.snapshot("test-1", root)["error"] == "backup_mount_marker_missing"
        assert module.snapshot("test-1", root / "missing")["error"] == "backup_root_not_mounted"
    (root / ".assessor-backup-mount").touch()
    class MissingVolume:
        returncode = 1
        stdout = ""
    with patch.object(module.subprocess, "run", return_value=MissingVolume()) as run:
        assert module.snapshot("test-1", root)["error"] == "source_volume_missing"
        assert run.call_count == 1
print("V5_ASSESSOR_VOLUME_FAIL_CLOSED=PASS")

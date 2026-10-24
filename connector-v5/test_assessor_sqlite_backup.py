#!/usr/bin/env python3
"""Offline tests: SQLite V5 primitive; no Docker, no production access."""
import importlib.util
from pathlib import Path
import sqlite3
import tarfile
import tempfile

spec = importlib.util.spec_from_file_location("assessor_sqlite_backup", Path(__file__).with_name("assessor_sqlite_backup.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="v5-assessor-sqlite-") as tmp:
    base = Path(tmp)
    db = base / "source.sqlite"
    storage = base / "storage"
    storage.mkdir()
    (storage / "document.txt").write_text("test-only", encoding="utf-8")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE trial_requests (id INTEGER PRIMARY KEY, state TEXT)")
        conn.execute("INSERT INTO trial_requests(state) VALUES ('requested')")
    bundle = base / "bundle"
    result = module.create_backup(db, storage, bundle)
    assert result["ok"] and result["table_count"] == 1
    assert module.verify(bundle)["sqlite_integrity"] == "ok"
    recovered = base / "recovered"
    module.restore_isolated(bundle, recovered)
    assert (recovered / "storage" / "document.txt").read_text() == "test-only"
    with sqlite3.connect(recovered / "database.sqlite") as conn:
        assert conn.execute("SELECT state FROM trial_requests").fetchone()[0] == "requested"
    try:
        module.restore_isolated(bundle, recovered)
    except ValueError as error:
        assert str(error) == "destination_exists"
    else:
        raise AssertionError("Restore unexpectedly overwrote destination")
    (bundle / "storage.tar.gz").write_bytes(b"corrupt")
    try:
        module.verify(bundle)
    except ValueError as error:
        assert str(error).startswith("checksum_mismatch:")
    else:
        raise AssertionError("Corrupt archive was accepted")
    print("V5_ASSESSOR_SQLITE_BACKUP_RESTORE=PASS")

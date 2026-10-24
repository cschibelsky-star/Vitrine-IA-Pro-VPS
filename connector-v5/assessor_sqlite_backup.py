"""Restricted SQLite backup/restore primitive for the V5 Assessor executor.

This module is intentionally independent of generic shell/compose execution.
Only the caller's allowlisted paths may be passed; restore never writes to
an existing destination. Production integration must mount the source volumes
read-only and use a separate isolated recovery target.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile
import tempfile


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(bundle: Path) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest.get("version") != 1:
        raise ValueError("unsupported_manifest")
    for name in ("database.sqlite", "storage.tar.gz"):
        if _hash(bundle / name) != manifest["sha256"][name]:
            raise ValueError("checksum_mismatch:" + name)
    with sqlite3.connect(f"file:{bundle / 'database.sqlite'}?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if integrity != "ok":
        raise ValueError("sqlite_integrity_failed")
    if tables < 1:
        raise ValueError("sqlite_has_no_tables")
    with tarfile.open(bundle / "storage.tar.gz", "r:gz") as archive:
        for item in archive.getmembers():
            p = PurePosixPath(item.name)
            if p.is_absolute() or ".." in p.parts or not (item.isfile() or item.isdir()):
                raise ValueError("unsafe_archive_member")
            if p.parts[0] != "storage":
                raise ValueError("unexpected_archive_root")
    return {"ok": True, "sqlite_integrity": "ok", "table_count": tables}


def create_backup(database: Path, storage: Path, destination: Path) -> dict:
    """Called only after manifest-based allowlist and read-only mount validation."""
    if not database.is_file() or not storage.is_dir():
        raise ValueError("source_missing")
    if destination.exists():
        raise ValueError("destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sqlite-backup-", dir=destination.parent) as tmp:
        stage = Path(tmp)
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source:
            with sqlite3.connect(stage / "database.sqlite") as target:
                source.backup(target)
        with tarfile.open(stage / "storage.tar.gz", "w:gz") as archive:
            archive.add(storage, arcname="storage", recursive=False)
            for entry in sorted(storage.rglob("*")):
                if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
                    raise ValueError("unsupported_storage_entry")
                archive.add(entry, arcname=str(PurePosixPath("storage") / entry.relative_to(storage)), recursive=False)
        manifest = {"version": 1, "sha256": {
            name: _hash(stage / name) for name in ("database.sqlite", "storage.tar.gz")
        }}
        (stage / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
        result = verify(stage)
        os.rename(stage, destination)
        return result


def restore_isolated(bundle: Path, destination: Path) -> dict:
    """Restores only to a NEW empty target, never an active runtime volume."""
    result = verify(bundle)
    if destination.exists():
        raise ValueError("destination_exists")
    destination.mkdir(parents=True)
    try:
        with (bundle / "database.sqlite").open("rb") as src:
            with (destination / "database.sqlite").open("xb") as out:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    out.write(block)
        with tarfile.open(bundle / "storage.tar.gz", "r:gz") as archive:
            for member in archive.getmembers():
                rel = PurePosixPath(member.name)
                target = destination.joinpath(*rel.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("xb") as out:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            out.write(block)
        return result
    except Exception:
        # Preserve failed target for forensic review, never delete user data.
        raise

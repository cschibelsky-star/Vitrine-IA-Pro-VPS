"""Restricted VIA backup verification. Not wired to the operational API yet.

The broker must mount the backup directory read-only and an isolated staging
directory read-write before exposing this function as an authenticated endpoint.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import tarfile

BACKUP_ROOT = Path("/srv/vitrine/backups/vps")
RESTORE_ROOT = Path("/srv/vitrine/restore-validation/via")
VIA_PREFIX = "srv/projects/via/"

def verify_via_backup(backup_name: str, expected_sha256: str, restore: bool = False) -> dict:
    if not isinstance(backup_name, str) or not backup_name.startswith("vps-filesystem-") or not backup_name.endswith(".tar.gz"):
        raise ValueError("Invalid backup name")
    if Path(backup_name).name != backup_name:
        raise ValueError("Backup must be a basename")
    archive = BACKUP_ROOT / backup_name
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("Backup unavailable")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256):
        raise ValueError("Invalid SHA-256")
    digest = hashlib.sha256()
    with archive.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected_sha256.lower():
        raise ValueError("Checksum mismatch")

    count = 0
    members = []
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            name = m.name.removeprefix("./")
            if not name.startswith(VIA_PREFIX):
                continue
            relative = name[len(VIA_PREFIX):]
            if not relative:
                continue
            parts = Path(relative).parts
            if (Path(relative).is_absolute() or ".." in parts or "." in parts or
                m.issym() or m.islnk() or m.isdev() or m.isfifo() or
                not (m.isdir() or m.isfile())):
                raise ValueError("Unsafe VIA archive entry")
            members.append((m, relative))
            count += 1
        if count == 0:
            raise ValueError("VIA files absent from backup")
        if restore:
            # Never restore in place or into a caller-selected path.
            if RESTORE_ROOT.is_symlink():
                raise ValueError("Restore root cannot be a symlink")
            root = RESTORE_ROOT / digest.hexdigest()[:20]
            if root.is_symlink() or root.exists():
                raise ValueError("Restore destination already exists")
            root.mkdir(parents=True, mode=0o700)
            for m, relative in members:
                dest = root / relative
                if not dest.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Unsafe destination")
                if m.isdir():
                    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    stream = tar.extractfile(m)
                    if stream is None:
                        raise ValueError("Unreadable archive member")
                    with stream, dest.open("xb") as output:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            output.write(block)
                    os.chmod(dest, 0o600)
    return {"ok": True, "backup": backup_name, "sha256_verified": True,
            "via_members": count, "restored": restore}

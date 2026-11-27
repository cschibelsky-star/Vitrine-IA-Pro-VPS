"""Private, online SQLite backup for the Assessor Online HML pilot."""
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from pathlib import Path

from assessor_snapshot import DESTINATION, DIR_FLAGS

PROJECT_ID = "assessor-online-pr137-current-hml"
COMPOSE_PROJECT = "assessor-pr137-current-hml"
SERVICE = "assessor_laravel"
CONTAINER = f"{COMPOSE_PROJECT}-{SERVICE}-1"
VOLUME = f"{COMPOSE_PROJECT}_assessor_laravel_storage"
STORAGE = "/var/www/html/storage"
VOLUME_DIR = Path("/var/lib/docker/volumes") / VOLUME / "_data"
MAX_BYTES = 128 * 1024 * 1024
MAX_BACKUPS = 5
BACKUP_SECONDS = 15


def locate_database(docker):
    template = ('{{.Id}}|{{index .Config.Labels "com.docker.compose.project"}}|'
                '{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{json .Mounts}}')
    cid, project, service, status, raw = docker(
        "inspect", "--type", "container", "--format", template, CONTAINER, timeout=5
    ).split("|", 4)
    if not re.fullmatch(r"[a-f0-9]{64}", cid) or (project, service, status) != (COMPOSE_PROJECT, SERVICE, "running"):
        raise PermissionError("container_not_allowed")
    mounts = [mount for mount in json.loads(raw) if mount.get("Destination") == STORAGE]
    if len(mounts) != 1 or any(mounts[0].get(k) != v for k, v in {
        "Type": "volume", "Name": VOLUME, "Source": str(VOLUME_DIR), "Driver": "local",
    }.items()):
        raise PermissionError("volume_not_allowed")
    return VOLUME_DIR / "assessor.sqlite"


def create_backup(docker):
    source = locate_database(docker)
    if source.resolve(strict=True) != source or not stat.S_ISREG(source.lstat().st_mode):
        raise PermissionError("database_not_allowed")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.is_symlink() or (sidecar.exists() and not stat.S_ISREG(sidecar.lstat().st_mode)):
            raise PermissionError("database_sidecar_not_allowed")
    directory = DESTINATION.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise PermissionError("unsafe_backup_directory")
    if sum(1 for _ in DESTINATION.glob("assessor-hml-db-*.sqlite")) >= MAX_BACKUPS:
        raise RuntimeError("backup_limit")

    fd, name = tempfile.mkstemp(prefix=".assessor-hml-db-", dir=DESTINATION)
    os.close(fd)
    temp = Path(name)
    deadline = time.monotonic() + BACKUP_SECONDS
    final = DESTINATION / (temp.name[1:] + ".sqlite")
    published = False
    complete = False

    def timed_out():
        return time.monotonic() > deadline

    def check_backup(_status, remaining, total):
        if timed_out() or max(remaining, total) * page_size > MAX_BYTES:
            raise RuntimeError("backup_budget_exceeded")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as live:
            page_size = live.execute("PRAGMA page_size").fetchone()[0]
            if live.execute("PRAGMA page_count").fetchone()[0] * page_size > MAX_BYTES:
                raise RuntimeError("backup_budget_exceeded")
            with closing(sqlite3.connect(temp, timeout=1)) as copy:
                live.backup(copy, pages=64, progress=check_backup, sleep=0.05)

        with closing(sqlite3.connect(temp.as_uri() + "?mode=ro", uri=True, timeout=1)) as copy:
            copy.set_progress_handler(lambda: int(timed_out()), 1000)
            if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("backup_integrity_failed")

        digest = hashlib.sha256()
        with temp.open("rb") as output:
            while chunk := output.read(1024 * 1024):
                if timed_out():
                    raise RuntimeError("backup_budget_exceeded")
                digest.update(chunk)
            size = output.tell()
            os.fsync(output.fileno())

        os.link(temp, final)
        published = True
        dirfd = os.open(DESTINATION, DIR_FLAGS)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        complete = True
        return {"archive": final.name, "sha256": digest.hexdigest(), "bytes": size,
                "integrity": "ok", "verified": True}
    finally:
        temp.unlink(missing_ok=True)
        if published and not complete:
            final.unlink(missing_ok=True)

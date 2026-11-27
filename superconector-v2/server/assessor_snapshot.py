"""Snapshot the fixed Assessor Online HML files on the VPS."""
import hashlib
import io
import os
import stat
import tarfile
import tempfile
from pathlib import Path

PROJECT = "assessor-online-pr137-current-hml"
ROOT = Path("/srv/projects") / PROJECT / "repository"
DESTINATION = Path("/var/lib/super-v2-maintenance")
FILES = (
    "app/Console/Commands/ProvisionAssessorHmlAdmin.php",
    "docker-compose.assessor-laravel-hml.yml",
    "hml/assessor-nginx.conf",
    "hml/assessor/demo.html",
    "routes/assessor_online.php",
)
MAX_FILE = 2 * 1024 * 1024
MAX_SNAPSHOTS = 20
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def read_fixed(base, parts):
    fd = os.open(base, DIR_FLAGS)
    try:
        for part in parts[:-1]:
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        with os.fdopen(os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                               dir_fd=fd), "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
                raise ValueError("invalid_source")
            data = source.read(MAX_FILE + 1)
            after = os.fstat(source.fileno())
            if (len(data) != before.st_size or len(data) > MAX_FILE
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns):
                raise ValueError("source_changed")
            return data
    finally:
        os.close(fd)


def create_snapshot():
    directory = DESTINATION.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise PermissionError("unsafe_snapshot_directory")
    if sum(1 for _ in DESTINATION.glob("assessor-hml-*.tar.gz")) >= MAX_SNAPSHOTS:
        raise ValueError("snapshot_limit")

    # Resolve every source component without following symlinks.
    sources = {
        name: read_fixed(Path("/"), (ROOT / name).parts[1:])
        for name in FILES
    }
    fd, temp = tempfile.mkstemp(prefix=".assessor-hml-", dir=DESTINATION)
    published = None
    complete = False
    try:
        with os.fdopen(fd, "w+b") as output:
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for name, data in sources.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o600
                    archive.addfile(info, io.BytesIO(data))
            output.flush()
            os.fsync(output.fileno())
            output.seek(0)
            with tarfile.open(fileobj=output, mode="r:gz") as archive:
                entries = archive.getmembers()
                if [entry.name for entry in entries] != list(FILES):
                    raise ValueError("invalid_snapshot_contents")
                for entry in entries:
                    with archive.extractfile(entry) as member:
                        if not entry.isfile() or member.read(MAX_FILE + 1) != sources[entry.name]:
                            raise ValueError("invalid_snapshot_contents")
            output.seek(0)
            digest = hashlib.sha256(output.read()).hexdigest()
            size = os.fstat(output.fileno()).st_size
        archive_name = Path(temp).name[1:] + ".tar.gz"
        final = DESTINATION / archive_name
        os.link(temp, final)
        published = final
        dirfd = os.open(DESTINATION, DIR_FLAGS)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        complete = True
    finally:
        Path(temp).unlink(missing_ok=True)
        if published is not None and not complete:
            published.unlink(missing_ok=True)
    return {"archive": archive_name, "sha256": digest, "bytes": size,
            "file_count": len(FILES), "verified": True}

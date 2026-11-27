"""Local, allowlisted maintenance broker for the Superconector HML candidate."""
import json
import logging
import os
import pwd
import re
import socket
import socketserver
import struct
import subprocess
from pathlib import Path

import assessor_snapshot
import hml_sqlite_backup
from hml_projects import PILOT, catalog

SOCKET = Path("/run/super-v2-maintenance/operations.sock")
TARGET = "vitrine-super-v2-operational-hml-operational_mcp-1"
PROJECT = "vitrine-super-v2-operational-hml"
SERVICE = "operational_mcp"
LOG = logging.getLogger("super-v2-maintenance")
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"}


def docker(*args, timeout=35):
    result = subprocess.run(
        ["/usr/bin/docker", "--host", "unix:///run/docker.sock", *args],
        env=ENV, cwd="/", shell=False, capture_output=True, text=True,
        timeout=timeout, check=True,
    )
    return result.stdout.strip()


def candidate():
    template = '{{.Id}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}'
    cid, project, service, status = docker("inspect", "--type", "container", "--format", template, TARGET).split("|")
    if not re.fullmatch(r"[0-9a-f]{64}", cid) or project != PROJECT or service != SERVICE:
        raise PermissionError("target_not_allowed")
    return cid, status


def operation(data):
    if not isinstance(data, dict):
        raise ValueError("invalid_request")
    if data.get("operation") in ("project_hml_snapshot", "project_hml_database_backup"):
        if set(data) != {"operation", "project_id"} or not isinstance(data["project_id"], str):
            raise ValueError("invalid_request")
        project = PILOT.get(data["project_id"])
        if project is None:
            raise PermissionError("project_not_allowed")
        if data["operation"] == "project_hml_database_backup":
            if project.project_id != hml_sqlite_backup.PROJECT_ID:
                raise PermissionError("database_backup_not_allowed")
            return {"ok": True, "operation": data["operation"], "target": project.project_id,
                    **hml_sqlite_backup.create_backup(docker)}
        return {"ok": True, "operation": "project_hml_snapshot", "target": project.project_id,
                **assessor_snapshot.create_snapshot(root=project.root, paths=project.snapshot_paths,
                                                   prefix=project.snapshot_prefix)}
    if set(data) != {"operation"}:
        raise ValueError("invalid_request")
    op = data["operation"]
    if op == "hml_project_catalog":
        return {"ok": True, "operation": op, "target": "hml-pilot", "projects": catalog()}
    if op == "assessor_hml_snapshot":
        return {"ok": True, "operation": op, "target": assessor_snapshot.PROJECT,
                **assessor_snapshot.create_snapshot()}
    if op not in ("candidate_status", "candidate_restart"):
        raise PermissionError("operation_not_allowed")
    cid, before = candidate()
    if op == "candidate_restart":
        docker("restart", "--time", "10", cid)
    after_id, after = candidate()
    if cid != after_id:
        raise RuntimeError("target_changed")
    if op == "candidate_restart" and after != "running":
        raise RuntimeError("candidate_not_running")
    return {"ok": True, "operation": op, "target": TARGET, "before": before, "after": after}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        uid = -1
        op = "invalid"
        try:
            _, uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            if uid != pwd.getpwnam("superv2ops").pw_uid:
                raise PermissionError("peer_not_allowed")
            raw = self.rfile.readline(1025)
            if len(raw) > 1024 or not raw.endswith(b"\n"):
                raise ValueError("invalid_request")
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("operation") in ("candidate_status", "candidate_restart", "assessor_hml_snapshot",
                                                                      "project_hml_snapshot", "hml_project_catalog", "project_hml_database_backup"):
                op = data["operation"]
            result = operation(data)
        except Exception:
            result = {"ok": False, "error": "denied_or_failed"}
        LOG.info("uid=%d operation=%s ok=%s", uid, op, result["ok"])
        self.wfile.write(json.dumps(result).encode() + b"\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    if SOCKET.parent.is_symlink() or SOCKET.parent.stat().st_uid != 0:
        raise RuntimeError("unsafe_socket_directory")
    if SOCKET.exists() or SOCKET.is_symlink():
        raise RuntimeError("socket_already_exists")
    with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

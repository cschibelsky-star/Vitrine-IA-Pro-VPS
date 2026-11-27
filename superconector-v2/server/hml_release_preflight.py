"""Read-only release preflight for explicitly registered HML services."""
import re
import subprocess

SHA = re.compile(r"[0-9a-f]{40}")


def git(root, *args):
    result = subprocess.run(
        ["/usr/bin/git", "--no-optional-locks", "-c", f"safe.directory={root}",
         "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=root, shell=False, capture_output=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        check=True,
    )
    return result.stdout


def runtime(docker, project, service):
    template = ('{{.Id}}|{{index .Config.Labels "com.docker.compose.project"}}|'
                '{{index .Config.Labels "com.docker.compose.service"}}|'
                '{{.Image}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}')
    ids = docker("ps", "--all", "--no-trunc", "--format", "{{.ID}}", "--filter",
                 f"label=com.docker.compose.project={project}", "--filter",
                 f"label=com.docker.compose.service={service}", timeout=4).splitlines()
    if len(ids) != 1:
        return {"service": service, "status": "absent" if not ids else "ambiguous"}
    if not re.fullmatch(r"[0-9a-f]{64}", ids[0]):
        raise RuntimeError("invalid_container_identity")
    cid, observed_project, observed_service, image, state, health = docker(
        "inspect", "--type", "container", "--format", template, ids[0], timeout=4
    ).split("|", 5)
    if (cid, observed_project, observed_service) != (ids[0], project, service):
        raise PermissionError("container_not_allowed")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("invalid_image_identity")
    return {"service": service, "container_id": cid, "current_image": image,
            "status": state, "health": health or None}


def preflight(project, requested_commit, docker):
    if not isinstance(requested_commit, str) or not SHA.fullmatch(requested_commit):
        raise ValueError("invalid_commit")
    root = project.root
    if root.resolve(strict=True) != root:
        raise PermissionError("repository_path_not_allowed")
    head = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    if not SHA.fullmatch(head):
        raise ValueError("invalid_workspace_head")
    changes = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal",
                  "--no-renames", "--ignore-submodules=dirty")
    try:
        commit_present = git(root, "cat-file", "-t", requested_commit).strip() == b"commit"
    except subprocess.CalledProcessError:
        commit_present = False
    services = [runtime(docker, project.docker_project, s) for s in project.services]
    return {
        "workspace_head": head,
        "workspace_dirty": bool(changes),
        "requested_commit": requested_commit,
        "commit_present_locally": commit_present,
        "services": services,
        "blockers": (
            (["workspace_has_local_changes"] if changes else [])
            + ([] if commit_present else ["commit_not_present_locally"])
            + (["runtime_service_unavailable"]
               if any(s["status"] != "running" or s.get("health") not in (None, "healthy")
                      for s in services) else [])
        ),
    }

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp-main")).resolve()
ROLLBACK_SOURCE = Path(os.getenv("ROLLBACK_SOURCE", "/srv/vitrine/backups/mcp-main-catalog/20260905-200451")).resolve()
ENV_FILE = ROOT / ".env.mcp-runtime"
BASE_COMPOSE = ROOT / "docker-compose.mcp.yml"
CATALOG_OVERRIDE = ROOT / "docker-compose.connector-v2.override.yml"
MAIN_OVERRIDE = ROOT / "docker-compose.main.override.yml"
PROJECT = "vitrine-vps-mcp-main"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
FAILED_SNAPSHOT = Path("/srv/vitrine/backups/mcp-main-cutover-failed") / STAMP


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, capture: bool = False) -> str:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), text=True, capture_output=capture, check=False)
    if capture:
        if proc.stdout:
            print(proc.stdout.rstrip(), flush=True)
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr, flush=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.stdout.strip() if capture else ""


def compose(*args: str) -> list[str]:
    return [
        "docker", "compose", "--env-file", str(ENV_FILE), "-p", PROJECT,
        "-f", str(BASE_COMPOSE), "-f", str(CATALOG_OVERRIDE), "-f", str(MAIN_OVERRIDE),
        *args,
    ]


def require(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"required path missing: {path}")


def wait_health(container: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", container],
            text=True, capture_output=True, check=False,
        )
        status = proc.stdout.strip().lower()
        if status != last:
            print(f"HEALTH {container}={status}", flush=True)
            last = status
        if status == "healthy":
            return
        if status in {"dead", "exited", "removing"}:
            raise RuntimeError(f"container {container} became {status}")
        time.sleep(2)
    raise TimeoutError(f"container {container} not healthy within {timeout}s")


def broker_get(path: str) -> dict:
    code = (
        "import os,json,urllib.request;"
        "t=os.environ['OPS_BROKER_TOKEN'];"
        f"r=urllib.request.Request('http://127.0.0.1:8770{path}',headers={{'Authorization':'Bearer '+t}});"
        "print(urllib.request.urlopen(r,timeout=30).read().decode())"
    )
    out = run(["docker", "exec", "vitrine_mcp_ops_broker", "python", "-c", code], capture=True)
    return json.loads(out.splitlines()[-1])


def mcp_registry_probe() -> None:
    image = run(["docker", "inspect", "--format", "{{.Config.Image}}", "vitrine_vps_mcp_connector"], capture=True).splitlines()[-1]
    network_json = run(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", "vitrine_vps_mcp_connector"], capture=True).splitlines()[-1]
    networks = json.loads(network_json)
    network = "vitrine_mcp_internal" if "vitrine_mcp_internal" in networks else next(iter(networks))
    required = [
        "system_health", "connector_health", "project_context", "project_manifest", "project_read_file",
        "project_write_file", "project_php_lint", "project_deploy", "via_health", "via_list_files",
        "via_read_file", "via_write_file", "via_execute_command", "hostgator_health", "hostgator_git_status",
        "hostgator_git_compare", "hostgator_read_file",
    ]
    cmd = [
        "docker", "run", "--rm", "--network", network, "--entrypoint", "python", image,
        "/app/probe_streamable_http.py", "--url", "http://vps_mcp_connector:8765/mcp",
        "--calls", "0", "--sessions", "1", "--catalog-only",
    ]
    for tool in required:
        cmd += ["--require-tool", tool]
    run(cmd)
    print("MCP_REGISTRY_GATE=PASS", flush=True)


def public_tls_gate() -> None:
    run(["curl", "-fsS", "--max-time", "20", "-H", "Accept: text/event-stream", "https://mcp.vitrineiapro.com.br/mcp"], check=False)
    proc = subprocess.run(
        "echo | openssl s_client -connect mcp.vitrineiapro.com.br:443 -servername mcp.vitrineiapro.com.br 2>/dev/null | openssl x509 -noout -subject -issuer -dates",
        shell=True, text=True, capture_output=True, check=False,
    )
    print(proc.stdout, end="", flush=True)
    if proc.returncode != 0 or "mcp.vitrineiapro.com.br" not in proc.stdout or "Let's Encrypt" not in proc.stdout:
        raise RuntimeError("public TLS gate failed")
    print("PUBLIC_TLS_GATE=PASS", flush=True)


def restore_source() -> None:
    print(f"ROLLBACK_SOURCE={ROLLBACK_SOURCE}", file=sys.stderr, flush=True)
    if not ROLLBACK_SOURCE.is_dir():
        raise RuntimeError(f"rollback source missing: {ROLLBACK_SOURCE}")
    FAILED_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    if ROOT.exists():
        shutil.copytree(ROOT, FAILED_SNAPSHOT, symlinks=True)
        for item in ROOT.iterdir():
            if item.name == ".env.mcp-runtime":
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
    for item in ROLLBACK_SOURCE.iterdir():
        target = ROOT / item.name
        if item.name == ".env.mcp-runtime" and ENV_FILE.exists():
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target, follow_symlinks=False)
    print(f"FAILED_CANDIDATE_SNAPSHOT={FAILED_SNAPSHOT}", file=sys.stderr, flush=True)


def rollback() -> None:
    print("ROLLBACK_START=SIM", file=sys.stderr, flush=True)
    restore_source()
    # Rollback source predates the catalog override; use only files that exist there.
    files = [BASE_COMPOSE]
    if (ROOT / "docker-compose.main.override.yml").exists():
        files.append(ROOT / "docker-compose.main.override.yml")
    cmd = ["docker", "compose", "--env-file", str(ENV_FILE), "-p", PROJECT]
    for f in files:
        cmd += ["-f", str(f)]
    cmd += ["up", "-d", "--build", "docker_socket_proxy", "ops_broker", "vps_mcp_connector"]
    run(cmd)
    wait_health("vitrine_mcp_ops_broker")
    wait_health("vitrine_vps_mcp_connector")
    print("ROLLBACK_COMPLETED=SIM", file=sys.stderr, flush=True)


def main() -> int:
    if os.getenv("CONFIRM") != "EXECUTAR":
        raise SystemExit("Use CONFIRM=EXECUTAR")
    for p in (ROOT, ROLLBACK_SOURCE, ENV_FILE, BASE_COMPOSE, CATALOG_OVERRIDE, MAIN_OVERRIDE, ROOT / "probe_streamable_http.py"):
        require(p)

    try:
        run(compose("config", "--quiet"))
        print("COMPOSE_CONFIG_GATE=PASS", flush=True)

        run(compose("build", "--no-cache", "ops_broker", "vps_mcp_connector"))
        print("BUILD_GATE=PASS", flush=True)

        run(compose("up", "-d", "docker_socket_proxy", "ops_broker", "vps_mcp_connector"))
        wait_health("vitrine_mcp_ops_broker")
        wait_health("vitrine_vps_mcp_connector")
        print("CONTAINER_HEALTH_GATE=PASS", flush=True)

        mcp_registry_probe()

        hostgator = broker_get("/hostgator/health")
        if not hostgator.get("ok"):
            raise RuntimeError(f"HostGator health failed: {hostgator}")
        print("HOSTGATOR_GATE=PASS", flush=True)

        via = broker_get("/via/health")
        print("VIA_HEALTH=" + json.dumps(via, ensure_ascii=False), flush=True)
        print("VIA_ROUTE_GATE=PASS", flush=True)

        public_tls_gate()

        print("MCP_MAIN_CUTOVER=PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"CUTOVER_FAILED={type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
        rollback()
        raise


if __name__ == "__main__":
    raise SystemExit(main())

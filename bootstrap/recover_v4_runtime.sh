#!/bin/sh
set -eu

RUNTIME="/srv/connectors/vitrine-vps-mcp"
BRANCH="feature/v4-hostgator-remote-ops"
REPO="https://github.com/cschibelsky-star/Vitrine-IA-Pro-VPS.git"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="/tmp/vitrine-v4-recover-$STAMP"
SNAP="/srv/backups/vitrine-vps-mcp-recover-$STAMP"

if [ ! -d "$RUNTIME" ]; then
  echo "RUNTIME_MISSING=$RUNTIME" >&2
  exit 1
fi

mkdir -p /srv/backups
cp -a "$RUNTIME" "$SNAP"
echo "RUNTIME_SNAPSHOT=$SNAP"

git clone --depth 1 --branch "$BRANCH" "$REPO" "$TMP"

CONNECTOR_ROOT="$RUNTIME" python3 "$TMP/connector-v2/install_connector_v2.py"
CONNECTOR_ROOT="$RUNTIME" python3 "$TMP/connector-v2/install_hostgator_remote_ops.py"
CONNECTOR_ROOT="$RUNTIME" python3 "$TMP/project-manager/install_project_manager.py"
CONNECTOR_ROOT="$RUNTIME" python3 "$TMP/bootstrap/install_v4_runtime_bind_mounts.py"

cd "$RUNTIME"
python3 -m py_compile ops_broker.py main.py v4_broker_entrypoint.py project_manager_operations.py project_read_operations.py project_shared_operations.py project_explicit_operations.py project_manager_tools.py

docker compose -p vitrine-vps-mcp \
  -f docker-compose.mcp.yml \
  -f docker-compose.connector-v2.override.yml \
  config --quiet

docker compose -p vitrine-vps-mcp \
  -f docker-compose.mcp.yml \
  -f docker-compose.connector-v2.override.yml \
  up -d --build --force-recreate ops_broker vps_mcp_connector

for i in $(seq 1 45); do
  STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' vitrine_mcp_ops_broker 2>/dev/null || true)"
  if [ "$STATUS" = "healthy" ]; then
    echo "OPS_BROKER_HEALTH=PASS"
    break
  fi
  if [ "$STATUS" = "dead" ] || [ "$STATUS" = "exited" ]; then
    echo "OPS_BROKER_HEALTH=FAIL:$STATUS" >&2
    docker logs --tail 120 vitrine_mcp_ops_broker 2>&1 || true
    exit 2
  fi
  sleep 2
done

echo "=== BROKER COMMAND ==="
docker inspect --format 'CMD={{json .Config.Cmd}}' vitrine_mcp_ops_broker || true

echo "=== ROUTER MODULES ==="
docker exec vitrine_mcp_ops_broker python - <<'PY' || true
import project_read_operations as r
import project_explicit_operations as e
import v4_broker_entrypoint as v4
print('READ_MODULE=' + str(r.__file__))
print('EXPLICIT_MODULE=' + str(e.__file__))
print('ENTRYPOINT_MODULE=' + str(v4.__file__))
print('READ_ROUTER_PATHS=' + repr([getattr(x,'path',None) for x in r.router.routes]))
print('EXPLICIT_ROUTER_PATHS=' + repr([getattr(x,'path',None) for x in e.router.routes]))
print('ENTRYPOINT_PATHS=' + repr([getattr(x,'path',None) for x in v4.app.routes]))
PY

echo "=== DIRECT BROKER OPENAPI ==="
docker exec vitrine_mcp_ops_broker python - <<'PY' || true
import json, urllib.request
try:
    data=json.load(urllib.request.urlopen('http://127.0.0.1:8770/openapi.json', timeout=5))
    print('\n'.join(sorted(data.get('paths',{}).keys())))
except Exception as exc:
    print('OPENAPI_ERROR=' + repr(exc))
PY

echo "=== MCP WRAPPER ==="
docker inspect --format 'CMD={{json .Config.Cmd}}' vitrine_vps_mcp_connector || true
docker exec vitrine_vps_mcp_connector python - <<'PY' || true
import inspect, project_manager_tools as p
print('TOOLS_MODULE=' + str(p.__file__))
print('FALLBACK=' + str(getattr(p,'OPS_API_FALLBACK',None)))
print('READ_SAFE_SOURCE=' + inspect.getsource(p.project_file_read_safe).strip())
PY

ROUTES="$(docker exec vitrine_mcp_ops_broker python -c 'import v4_broker_entrypoint as v4; print("\n".join(sorted({getattr(r,"path","") for r in v4.app.routes})))' 2>/dev/null || true)"
echo "=== BROKER ROUTES ==="
printf '%s\n' "$ROUTES"
printf '%s\n' "$ROUTES" | grep -qx '/projects/read-file' || { echo 'ROUTE_READ_FILE=MISSING' >&2; exit 3; }
printf '%s\n' "$ROUTES" | grep -qx '/projects/file/read-safe' || { echo 'ROUTE_FILE_READ_SAFE=MISSING' >&2; exit 3; }
printf '%s\n' "$ROUTES" | grep -qx '/projects/file/patch-text' || { echo 'ROUTE_FILE_PATCH_TEXT=MISSING' >&2; exit 3; }
printf '%s\n' "$ROUTES" | grep -qx '/projects/compose/explicit' || { echo 'ROUTE_COMPOSE_EXPLICIT=MISSING' >&2; exit 3; }
printf '%s\n' "$ROUTES" | grep -qx '/projects/git/stage' || { echo 'ROUTE_GIT_STAGE=MISSING' >&2; exit 3; }
printf '%s\n' "$ROUTES" | grep -qx '/projects/git/commit' || { echo 'ROUTE_GIT_COMMIT=MISSING' >&2; exit 3; }

echo "V4_EXPLICIT_ROUTES=PASS"
echo "V4_RUNTIME_RECOVERY=PASS"
rm -rf "$TMP"

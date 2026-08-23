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

echo "=== DIRECT BROKER OPENAPI ==="
OPENAPI_PATHS="$(docker exec vitrine_mcp_ops_broker python -c 'import json, urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:8770/openapi.json", timeout=5)); print("\n".join(sorted(data.get("paths",{}).keys())))')"
printf '%s\n' "$OPENAPI_PATHS"

for required in \
  /projects/read-file \
  /projects/file/read-safe \
  /projects/file/patch-text \
  /projects/compose/explicit \
  /projects/git/stage \
  /projects/git/commit
 do
  printf '%s\n' "$OPENAPI_PATHS" | grep -qx "$required" || { echo "ROUTE_MISSING=$required" >&2; exit 3; }
done

echo "V4_EXPLICIT_ROUTES=PASS"

echo "=== MCP INTERNAL READ SAFE ==="
docker exec vitrine_vps_mcp_connector python -c 'import json, project_manager_tools as p; print("OPS_API_URL="+p.OPS_API_URL); print("OPS_BROKER_URL="+p.OPS_BROKER_URL); print(json.dumps(p.project_file_read_safe("vitrine-ia-pro-core","bootstrap/app.php",1,20), ensure_ascii=False))'

echo "V4_MCP_INTERNAL_CALL=PASS"
echo "V4_RUNTIME_RECOVERY=PASS"
rm -rf "$TMP"

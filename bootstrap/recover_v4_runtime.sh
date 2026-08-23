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

cd "$RUNTIME"
python3 -m py_compile ops_broker.py main.py project_manager_operations.py project_read_operations.py project_shared_operations.py project_explicit_operations.py project_manager_tools.py

docker compose -p vitrine-vps-mcp \
  -f docker-compose.mcp.yml \
  -f docker-compose.connector-v2.override.yml \
  config --quiet

docker compose -p vitrine-vps-mcp \
  -f docker-compose.mcp.yml \
  -f docker-compose.connector-v2.override.yml \
  up -d --build ops_broker vps_mcp_connector

for i in $(seq 1 45); do
  STATUS="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' vitrine_mcp_ops_broker 2>/dev/null || true)"
  if [ "$STATUS" = "healthy" ]; then
    echo "OPS_BROKER_HEALTH=PASS"
    echo "V4_RUNTIME_RECOVERY=PASS"
    rm -rf "$TMP"
    exit 0
  fi
  if [ "$STATUS" = "dead" ] || [ "$STATUS" = "exited" ]; then
    break
  fi
  sleep 2
done

echo "V4_RUNTIME_RECOVERY=FAIL" >&2
exit 2

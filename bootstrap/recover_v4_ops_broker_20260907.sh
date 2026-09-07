#!/bin/sh
set -eu

RUNTIME=/srv/connectors/vitrine-vps-mcp
SOURCE=/srv/projects/vitrine-vps-mcp/repository
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SNAPSHOT=/srv/vitrine/security-snapshots/v4-recovery-$STAMP

printf '%s\n' '=== V4 OPS BROKER RECOVERY ==='
printf 'runtime=%s\nsource=%s\nsnapshot=%s\n' "$RUNTIME" "$SOURCE" "$SNAPSHOT"

[ -d "$RUNTIME" ] || { echo 'ERROR: runtime_missing'; exit 10; }
[ -d "$SOURCE/.git" ] || { echo 'ERROR: source_repo_missing'; exit 11; }
[ -f "$SOURCE/docker-compose.ops-api.yml" ] || { echo 'ERROR: recovery_compose_missing'; exit 12; }
[ -f "$SOURCE/bootstrap/repair_v4_tvsumare_router.py" ] || { echo 'ERROR: router_repair_missing'; exit 13; }

mkdir -p "$SNAPSHOT"
cp -a "$RUNTIME" "$SNAPSHOT/runtime"
git -C "$SOURCE" status --short --branch > "$SNAPSHOT/source-git-status.txt"
git -C "$SOURCE" rev-parse HEAD > "$SNAPSHOT/source-head.txt"
docker ps -a --no-trunc > "$SNAPSHOT/docker-ps-before.txt"

printf '%s\n' '--- source preflight ---'
git -C "$SOURCE" status --short --branch

printf '%s\n' '--- repair legacy broker anchors ---'
docker run --rm \
  -e CONNECTOR_ROOT=/runtime \
  -v "$RUNTIME:/runtime:rw" \
  -v "$SOURCE:/source:ro" \
  python:3.12-alpine \
  python /source/bootstrap/repair_v4_tvsumare_router.py

printf '%s\n' '--- install V4 runtime from source ---'
docker compose \
  -p vitrine-v4-recovery \
  -f "$SOURCE/docker-compose.ops-api.yml" \
  run --rm --no-deps connector_self_update_install

printf '%s\n' '--- rebuild only ops_broker + vps_mcp_connector ---'
docker compose \
  -p vitrine-v4-recovery \
  -f "$SOURCE/docker-compose.ops-api.yml" \
  run --rm --no-deps connector_self_update_rebuild

printf '%s\n' '--- postflight ---'
docker ps -a --filter name=vitrine_vps_mcp --filter name=ops_broker --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

printf '%s\n' '--- local health ---'
if curl -fsS --max-time 5 http://127.0.0.1:8770/health >/tmp/v4-health.json 2>/tmp/v4-health.err; then
  cat /tmp/v4-health.json
else
  cat /tmp/v4-health.err >&2 || true
fi

printf '%s\n' 'V4_RECOVERY_BOOTSTRAP_COMPLETE'

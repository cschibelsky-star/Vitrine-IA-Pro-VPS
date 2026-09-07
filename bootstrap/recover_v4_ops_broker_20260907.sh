#!/bin/sh
set -eu

RUNTIME=/srv/connectors/vitrine-vps-mcp
SOURCE=/srv/projects/vitrine-vps-mcp/repository
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SNAPSHOT=/srv/vitrine/security-snapshots/v4-recovery-$STAMP
CUTOVER_FILE="$SNAPSHOT/cutover-containers.tsv"
CUTOVER_DONE=0

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
: > "$CUTOVER_FILE"

rollback_cutover() {
  code=$?
  if [ "$CUTOVER_DONE" -eq 1 ]; then
    exit "$code"
  fi
  echo '--- rollback V4 cutover ---' >&2
  for name in vitrine_mcp_ops_broker vitrine_mcp_docker_proxy vitrine_vps_mcp_connector; do
    if docker container inspect "$name" >/dev/null 2>&1; then
      docker rm -f "$name" >/dev/null 2>&1 || true
    fi
  done
  if [ -s "$CUTOVER_FILE" ]; then
    while IFS="	" read -r original preserved was_running; do
      [ -n "$original" ] || continue
      if docker container inspect "$preserved" >/dev/null 2>&1; then
        docker rename "$preserved" "$original" >/dev/null 2>&1 || true
        if [ "$was_running" = "true" ]; then
          docker start "$original" >/dev/null 2>&1 || true
        fi
      fi
    done < "$CUTOVER_FILE"
  fi
  exit "$code"
}
trap rollback_cutover EXIT INT TERM

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

printf '%s\n' '--- preserve legacy V4 containers before cutover ---'
for name in vitrine_mcp_ops_broker vitrine_mcp_docker_proxy vitrine_vps_mcp_connector; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    running=$(docker inspect -f '{{.State.Running}}' "$name")
    preserved="${name}_pre_v4_${STAMP}"
    docker inspect "$name" > "$SNAPSHOT/${name}.inspect.json"
    docker rename "$name" "$preserved"
    printf '%s\t%s\t%s\n' "$name" "$preserved" "$running" >> "$CUTOVER_FILE"
    if [ "$running" = "true" ]; then
      docker stop --time 15 "$preserved" >/dev/null
    fi
    echo "PRESERVED_CONTAINER=$name->$preserved running=$running"
  fi
done

printf '%s\n' '--- rebuild only ops_broker + vps_mcp_connector ---'
docker compose \
  -p vitrine-v4-recovery \
  -f "$SOURCE/docker-compose.ops-api.yml" \
  run --rm --no-deps connector_self_update_rebuild

printf '%s\n' '--- validate new V4 containers ---'
for name in vitrine_mcp_ops_broker vitrine_vps_mcp_connector; do
  ok=0
  i=0
  while [ "$i" -lt 45 ]; do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)
    if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
      echo "V4_CONTAINER_HEALTH=$name:$status"
      ok=1
      break
    fi
    if [ "$status" = "dead" ] || [ "$status" = "exited" ]; then
      break
    fi
    i=$((i + 1))
    sleep 2
  done
  if [ "$ok" -ne 1 ]; then
    echo "ERROR: container_not_healthy:$name:$status" >&2
    docker logs --tail 120 "$name" >&2 2>&1 || true
    exit 20
  fi
done

printf '%s\n' '--- validate broker internally ---'
docker exec vitrine_mcp_ops_broker python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8770/openapi.json",timeout=5)); p=d.get("paths",{}); required=["/health","/projects/compose/explicit","/containers/{name}/status","/containers/{name}/logs"]; missing=[x for x in required if x not in p]; print("V4_OPENAPI_PATHS="+str(len(p))); print("V4_REQUIRED_MISSING="+",".join(missing)); raise SystemExit(1 if missing else 0)'

printf '%s\n' '--- postflight ---'
docker ps -a --filter name=vitrine_vps_mcp --filter name=vitrine_mcp_ops_broker --filter name=vitrine_mcp_docker_proxy --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

CUTOVER_DONE=1
trap - EXIT INT TERM
printf '%s\n' "V4_RECOVERY_BOOTSTRAP_COMPLETE snapshot=$SNAPSHOT"

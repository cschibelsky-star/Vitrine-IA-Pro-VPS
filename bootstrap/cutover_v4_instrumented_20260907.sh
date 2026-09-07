#!/bin/sh
set -eu

RUNTIME=/srv/connectors/vitrine-vps-mcp
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SNAPSHOT=/srv/vitrine/security-snapshots/v4-cutover-$STAMP
PRESERVED="$SNAPSHOT/preserved.txt"
CUTOVER_OK=0

mkdir -p "$SNAPSHOT"
: > "$PRESERVED"

echo '=== V4 CONTROLLED CUTOVER (INSTRUMENTED) ==='
echo "snapshot=$SNAPSHOT"

OPS_BROKER_TOKEN=$(
  docker inspect vitrine_mcp_ops_broker \
    --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | sed -n 's/^OPS_BROKER_TOKEN=//p' \
  | head -1
)

if [ -z "$OPS_BROKER_TOKEN" ]; then
  echo 'ERROR: OPS_BROKER_TOKEN vazio' >&2
  exit 10
fi
export OPS_BROKER_TOKEN

capture_failed_cutover() {
  echo '--- capture failed V4 cutover evidence ---' >&2
  for name in vitrine_mcp_ops_broker vitrine_mcp_docker_proxy vitrine_vps_mcp_connector; do
    if docker inspect "$name" >/dev/null 2>&1; then
      docker inspect "$name" > "$SNAPSHOT/${name}.failed.inspect.json" 2>/dev/null || true
      docker logs --tail 500 "$name" > "$SNAPSHOT/${name}.failed.log" 2>&1 || true
      docker inspect -f '{{json .State.Health}}' "$name" > "$SNAPSHOT/${name}.failed.health.json" 2>/dev/null || true
    fi
  done
  docker ps -a --no-trunc > "$SNAPSHOT/docker-ps-failed-cutover.txt" 2>/dev/null || true
}

rollback() {
  code=$?
  if [ "$CUTOVER_OK" -eq 1 ]; then
    exit "$code"
  fi

  capture_failed_cutover
  echo '=== ROLLBACK V4 ===' >&2

  for name in vitrine_mcp_ops_broker vitrine_mcp_docker_proxy vitrine_vps_mcp_connector; do
    docker rm -f "$name" >/dev/null 2>&1 || true
  done

  if [ -s "$PRESERVED" ]; then
    while IFS='|' read -r original saved running; do
      [ -n "$original" ] || continue
      if docker inspect "$saved" >/dev/null 2>&1; then
        docker rename "$saved" "$original"
        if [ "$running" = 'true' ]; then
          docker start "$original" >/dev/null
        fi
      fi
    done < "$PRESERVED"
  fi

  echo 'ROLLBACK_V4=COMPLETE' >&2
  echo "failure_snapshot=$SNAPSHOT" >&2
  exit "$code"
}
trap rollback EXIT INT TERM

echo '--- preflight compose ---'
docker compose \
  -p vitrine-vps-mcp \
  -f "$RUNTIME/docker-compose.mcp.yml" \
  -f "$RUNTIME/docker-compose.connector-v2.override.yml" \
  config >/dev/null

echo '--- preservar runtime atual ---'
for name in vitrine_mcp_ops_broker vitrine_mcp_docker_proxy vitrine_vps_mcp_connector; do
  if docker inspect "$name" >/dev/null 2>&1; then
    running=$(docker inspect -f '{{.State.Running}}' "$name")
    saved="${name}_pre_cutover_${STAMP}"

    docker inspect "$name" > "$SNAPSHOT/${name}.inspect.json"
    docker logs --tail 300 "$name" > "$SNAPSHOT/${name}.log" 2>&1 || true

    docker rename "$name" "$saved"
    if [ "$running" = 'true' ]; then
      docker stop --time 15 "$saved" >/dev/null
    fi

    printf '%s|%s|%s\n' "$name" "$saved" "$running" >> "$PRESERVED"
    echo "PRESERVED=$name->$saved"
  fi
done

echo '--- rebuild somente V4 ---'
docker compose \
  -p vitrine-vps-mcp \
  -f "$RUNTIME/docker-compose.mcp.yml" \
  -f "$RUNTIME/docker-compose.connector-v2.override.yml" \
  up -d --build ops_broker vps_mcp_connector

echo '--- validar health ---'
for name in vitrine_mcp_ops_broker vitrine_vps_mcp_connector; do
  ok=0
  i=0

  while [ "$i" -lt 60 ]; do
    status=$(
      docker inspect \
        -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$name" 2>/dev/null || true
    )

    if [ "$status" = 'healthy' ]; then
      echo "V4_HEALTH=$name:healthy"
      ok=1
      break
    fi

    if [ "$status" = 'dead' ] || [ "$status" = 'exited' ]; then
      break
    fi

    i=$((i + 1))
    sleep 2
  done

  if [ "$ok" -ne 1 ]; then
    echo "ERROR: $name status=$status" >&2
    exit 20
  fi
done

echo '--- validar broker ---'
docker exec vitrine_mcp_ops_broker \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8770/health",timeout=5).read().decode())'

echo '--- validar Docker CLI ---'
docker exec vitrine_mcp_ops_broker docker --version

echo '--- validar Compose ---'
docker exec vitrine_mcp_ops_broker sh -c \
  'docker compose version 2>/dev/null || docker-compose --version'

echo '--- validar rotas de diagnostico ---'
docker exec vitrine_mcp_ops_broker python -c '
import json, urllib.request
d=json.load(urllib.request.urlopen("http://127.0.0.1:8770/openapi.json",timeout=5))
p=d.get("paths",{})
required=[
 "/health",
 "/projects/compose/explicit",
 "/containers/{name}/status",
 "/containers/{name}/logs",
]
missing=[x for x in required if x not in p]
print("V4_REQUIRED_MISSING="+",".join(missing))
raise SystemExit(1 if missing else 0)
'

echo '--- validar manifesto V5 na nova imagem ---'
docker exec vitrine_vps_mcp_connector \
  test -f /app/project-manifests/vitrine-vps-mcp-v59-integration.json

echo 'V5_MANIFEST_IMAGE=PASS'

echo '--- estado final ---'
docker ps \
  --filter name=vitrine_mcp_ops_broker \
  --filter name=vitrine_vps_mcp_connector \
  --filter name=vitrine_mcp_docker_proxy \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

CUTOVER_OK=1
trap - EXIT INT TERM

echo
echo 'V4_CONTROLLED_CUTOVER=PASS'
echo "snapshot=$SNAPSHOT"

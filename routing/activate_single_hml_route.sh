#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-}"
route_id="${ROUTE_ID:-}"

if [ -z "$repo_root" ] || [ ! -d "$repo_root" ]; then
  echo "ERROR invalid_repository_root" >&2
  exit 2
fi
if ! [[ "$route_id" =~ ^[a-z0-9_-]+$ ]]; then
  echo "ERROR invalid_route_id" >&2
  exit 3
fi

registry="$repo_root/routing/routes.json"
if [ ! -f "$registry" ]; then
  echo "ERROR registry_missing" >&2
  exit 4
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR python3_unavailable" >&2
  exit 5
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR docker_unavailable" >&2
  exit 6
fi

route_json="$(python3 - "$registry" "$route_id" <<'PY'
import json, sys
p, rid = sys.argv[1:3]
with open(p, encoding='utf-8') as fh:
    data = json.load(fh)
route = next((r for r in data.get('routes', []) if r.get('id') == rid), None)
if route is None:
    raise SystemExit(10)
required = ['hostname', 'upstream', 'network', 'environment', 'ssl', 'cert_resolver', 'entrypoint', 'status']
if any(k not in route for k in required):
    raise SystemExit(11)
if route['environment'] != 'homologation' or route['ssl'] is not True:
    raise SystemExit(12)
if route['status'] not in ('pending_dns_proxy', 'active'):
    raise SystemExit(13)
print(json.dumps(route, separators=(',', ':')))
PY
)" || {
  rc=$?
  echo "ERROR route_registry_validation_failed rc=$rc" >&2
  exit "$rc"
}

readarray -t fields < <(python3 - "$route_json" <<'PY'
import json, re, sys
r=json.loads(sys.argv[1])
hostname=str(r['hostname'])
upstream=str(r['upstream'])
network=str(r['network'])
resolver=str(r['cert_resolver'])
entrypoint=str(r['entrypoint'])
if not hostname.endswith('.vitrineiapro.com.br'):
    raise SystemExit(20)
m=re.fullmatch(r'http://([A-Za-z0-9_.-]+):([0-9]{1,5})', upstream)
if not m:
    raise SystemExit(21)
port=int(m.group(2))
if port < 1 or port > 65535:
    raise SystemExit(22)
for value in (hostname, m.group(1), network, resolver, entrypoint, str(port)):
    print(value)
PY
) || {
  rc=$?
  echo "ERROR route_field_validation_failed rc=$rc" >&2
  exit "$rc"
}

hostname="${fields[0]}"
target_container="${fields[1]}"
network="${fields[2]}"
resolver="${fields[3]}"
entrypoint="${fields[4]}"
target_port="${fields[5]}"
upstream="http://${target_container}:${target_port}"

if [ "$network" != "vitrine_net" ]; then
  echo "ERROR network_not_allowed" >&2
  exit 23
fi
if [ "$entrypoint" != "websecure" ]; then
  echo "ERROR entrypoint_not_allowed" >&2
  exit 24
fi

if ! docker inspect traefik >/dev/null 2>&1; then
  echo "ERROR traefik_container_unavailable" >&2
  exit 30
fi
if ! docker inspect "$target_container" >/dev/null 2>&1; then
  echo "ERROR target_container_unavailable container=$target_container" >&2
  exit 31
fi

running="$(docker inspect "$target_container" --format '{{.State.Running}}')"
if [ "$running" != "true" ]; then
  echo "ERROR target_container_not_running container=$target_container" >&2
  exit 32
fi

if ! docker inspect "$target_container" --format '{{json .NetworkSettings.Networks}}' | grep -q '"vitrine_net"'; then
  echo "ERROR target_not_on_vitrine_net container=$target_container" >&2
  exit 33
fi

# Traefik must share the application network in order to resolve the explicit
# Docker service URL used below. Fail closed instead of modifying Traefik.
if ! docker inspect traefik --format '{{json .NetworkSettings.Networks}}' | grep -q '"vitrine_net"'; then
  echo "ERROR traefik_not_on_vitrine_net" >&2
  exit 34
fi

carrier="vitrine_route_${route_id}"
image="alpine:3.20"

if docker inspect "$carrier" >/dev/null 2>&1; then
  current_route="$(docker inspect "$carrier" --format '{{index .Config.Labels "vitrine.route.id"}}' 2>/dev/null || true)"
  if [ "$current_route" != "$route_id" ]; then
    echo "ERROR route_carrier_name_collision" >&2
    exit 35
  fi
  docker rm -f "$carrier" >/dev/null
fi

docker run -d \
  --name "$carrier" \
  --restart unless-stopped \
  --network "$network" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --label "vitrine.route.id=$route_id" \
  --label "vitrine.route.hostname=$hostname" \
  --label "vitrine.route.upstream=$upstream" \
  --label "traefik.enable=true" \
  --label "traefik.docker.network=$network" \
  --label "traefik.http.routers.${route_id}.rule=Host(\`${hostname}\`)" \
  --label "traefik.http.routers.${route_id}.entrypoints=${entrypoint}" \
  --label "traefik.http.routers.${route_id}.tls=true" \
  --label "traefik.http.routers.${route_id}.tls.certresolver=${resolver}" \
  --label "traefik.http.routers.${route_id}.service=${route_id}" \
  --label "traefik.http.services.${route_id}.loadbalancer.server.url=${upstream}" \
  "$image" sh -c 'exec sleep infinity' >/dev/null

sleep 2
state="$(docker inspect "$carrier" --format '{{.State.Status}}')"
if [ "$state" != "running" ]; then
  echo "ERROR route_carrier_not_running status=$state" >&2
  exit 40
fi

echo "ROUTE_ACTIVE id=$route_id hostname=$hostname upstream=$upstream carrier=$carrier"

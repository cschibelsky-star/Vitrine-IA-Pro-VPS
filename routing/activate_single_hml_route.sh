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
import json, sys
r=json.loads(sys.argv[1])
for k in ('hostname','upstream','network','cert_resolver','entrypoint'):
    print(str(r[k]))
PY
)
hostname="${fields[0]}"
upstream="${fields[1]}"
network="${fields[2]}"
resolver="${fields[3]}"
entrypoint="${fields[4]}"

if [[ "$hostname" != *.vitrineiapro.com.br ]]; then
  echo "ERROR hostname_not_allowed" >&2
  exit 20
fi
if [[ "$upstream" != http://tvsumare_web:80 ]]; then
  echo "ERROR upstream_not_allowed" >&2
  exit 21
fi
if [ "$network" != "vitrine_net" ]; then
  echo "ERROR network_not_allowed" >&2
  exit 22
fi
if [ "$entrypoint" != "websecure" ]; then
  echo "ERROR entrypoint_not_allowed" >&2
  exit 23
fi

if ! docker inspect traefik >/dev/null 2>&1; then
  echo "ERROR traefik_container_unavailable" >&2
  exit 30
fi
if ! docker inspect tvsumare_web >/dev/null 2>&1; then
  echo "ERROR tvsumare_container_unavailable" >&2
  exit 31
fi

if ! docker inspect tvsumare_web --format '{{json .NetworkSettings.Networks}}' | grep -q '"vitrine_net"'; then
  echo "ERROR tvsumare_not_on_vitrine_net" >&2
  exit 32
fi

# Prefer the Docker provider: connect Traefik directly to the already-running
# tvsumare_web container by applying labels to a tiny route-carrier container.
# This avoids rewriting the application container and keeps the route isolated.
carrier="vitrine_route_${route_id}"
image="alpine:3.20"

# Do not replace an unrelated container with the same name.
if docker inspect "$carrier" >/dev/null 2>&1; then
  current_route="$(docker inspect "$carrier" --format '{{index .Config.Labels "vitrine.route.id"}}' 2>/dev/null || true)"
  if [ "$current_route" != "$route_id" ]; then
    echo "ERROR route_carrier_name_collision" >&2
    exit 33
  fi
  docker rm -f "$carrier" >/dev/null
fi

# Traefik resolves the service URL through the shared Docker network. The
# carrier itself is inert; labels declare a router whose service points to the
# TV Sumare container through a file-less load balancer URL.
docker run -d \
  --name "$carrier" \
  --restart unless-stopped \
  --network "$network" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --label "vitrine.route.id=$route_id" \
  --label "traefik.enable=true" \
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

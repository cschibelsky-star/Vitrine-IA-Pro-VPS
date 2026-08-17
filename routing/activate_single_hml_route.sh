#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"
ROUTE_ID="${ROUTE_ID:-}"
EXPECTED_IP="${EXPECTED_IP:-143.95.219.238}"
NGINX_CONF_ROOT="${NGINX_CONF_ROOT:-/srv/vitrine/docker/nginx/conf.d}"
NGINX_HTML_ROOT="${NGINX_HTML_ROOT:-/srv/vitrine/docker/nginx/html}"
SSL_ROOT="${VITRINE_SSL_ROOT:-/srv/vitrine/ssl}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:latest}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

fail() { echo "ERRO: $*" >&2; exit 1; }
info() { echo "[activate-single-hml] $*"; }

[[ -n "$ROUTE_ID" ]] || fail "ROUTE_ID obrigatorio"
[[ -n "$CERTBOT_EMAIL" ]] || fail "CERTBOT_EMAIL obrigatorio"
[[ -f "$ROOT/routing/routes.json" ]] || fail "routing/routes.json ausente"

docker inspect vitrine_nginx >/dev/null 2>&1 || fail "container vitrine_nginx nao encontrado"
docker network inspect vitrine_net >/dev/null 2>&1 || fail "rede vitrine_net nao encontrada"

python3 "$ROOT/routing/validate_routes.py" "$ROOT/routing/routes.json"
python3 "$ROOT/routing/dns_preflight.py" --expected-ip "$EXPECTED_IP" --registry "$ROOT/routing/routes.json" --route-id "$ROUTE_ID"

route_json="$(python3 - "$ROOT/routing/routes.json" "$ROUTE_ID" <<'PY'
import json, sys
path, route_id = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding='utf-8'))
for route in data['routes']:
    if route['id'] == route_id:
        print(json.dumps(route, ensure_ascii=False))
        raise SystemExit(0)
raise SystemExit(1)
PY
)" || fail "route-id nao encontrado: $ROUTE_ID"

host="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["hostname"])' "$route_json")"
health_path="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["health_path"])' "$route_json")"
upstream="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["upstream"])' "$route_json")"

info "rota: $ROUTE_ID"
info "host: $host"
info "upstream: $upstream"
info "health: $health_path"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="/srv/vitrine/backups/routing/$stamp"
target="$NGINX_CONF_ROOT/$ROUTE_ID.conf"
mkdir -p "$backup_root" "$NGINX_CONF_ROOT" "$NGINX_HTML_ROOT" "$SSL_ROOT"
[[ -f "$target" ]] && cp -a "$target" "$backup_root/$ROUTE_ID.conf"

rollback() {
  rc=$?
  info "falha detectada; iniciando rollback"
  if [[ -f "$backup_root/$ROUTE_ID.conf" ]]; then
    cp -a "$backup_root/$ROUTE_ID.conf" "$target"
  else
    rm -f "$target"
  fi
  docker exec vitrine_nginx nginx -t >/dev/null 2>&1 || true
  docker exec vitrine_nginx nginx -s reload >/dev/null 2>&1 || true
  exit "$rc"
}
trap rollback ERR

http_stage="$(mktemp -d)"
https_stage="$(mktemp -d)"
cleanup() { rm -rf "$http_stage" "$https_stage"; }
trap cleanup EXIT

python3 "$ROOT/routing/generate_nginx.py" "$ROOT/routing/routes.json" --phase http --route-id "$ROUTE_ID" --output "$http_stage"
cp "$http_stage/$ROUTE_ID.conf" "$target"
docker exec vitrine_nginx nginx -t
docker exec vitrine_nginx nginx -s reload

info "emitindo certificado dedicado para $host"
docker run --rm \
  -v "$SSL_ROOT:/etc/letsencrypt" \
  -v "$NGINX_HTML_ROOT:/usr/share/nginx/html" \
  "$CERTBOT_IMAGE" certonly \
  --webroot --webroot-path /usr/share/nginx/html \
  --cert-name "$host" --domain "$host" --email "$CERTBOT_EMAIL" \
  --agree-tos --non-interactive --no-eff-email --force-renewal

[[ -s "$SSL_ROOT/live/$host/fullchain.pem" ]] || fail "fullchain ausente para $host"
[[ -s "$SSL_ROOT/live/$host/privkey.pem" ]] || fail "privkey ausente para $host"

python3 "$ROOT/routing/generate_nginx.py" "$ROOT/routing/routes.json" --phase full --route-id "$ROUTE_ID" --output "$https_stage"
cp "$https_stage/$ROUTE_ID.conf" "$target"
docker exec vitrine_nginx nginx -t
docker exec vitrine_nginx nginx -s reload

python3 - "$host" "$health_path" <<'PY'
import ssl, sys, urllib.request
host, health = sys.argv[1], sys.argv[2]
url = f"https://{host}{health}"
ctx = ssl.create_default_context()
with urllib.request.urlopen(url, timeout=20, context=ctx) as response:
    if response.status != 200:
        raise SystemExit(f"{url}: status {response.status}, esperado 200")
    print(f"OK {url} -> {response.status}")
PY

trap - ERR
info "rota publicada com sucesso: https://$host"
info "backup de rollback: $backup_root"

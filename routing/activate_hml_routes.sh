#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"
EXPECTED_IP="${EXPECTED_IP:-143.95.219.238}"
NGINX_CONF_ROOT="${NGINX_CONF_ROOT:-/srv/vitrine/docker/nginx/conf.d}"
NGINX_HTML_ROOT="${NGINX_HTML_ROOT:-/srv/vitrine/docker/nginx/html}"
SSL_ROOT="${VITRINE_SSL_ROOT:-/srv/vitrine/ssl}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:latest}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
SECRETS_FILE="${HML_CENTER_ENV_FILE:-/srv/vitrine/secrets/hml-center.env}"
ROUTES=("vitrine-hml-center" "cursos-ia-hml")

fail() { echo "ERRO: $*" >&2; exit 1; }
info() { echo "[activate-hml] $*"; }

[[ -n "$CERTBOT_EMAIL" ]] || fail "CERTBOT_EMAIL obrigatorio"
[[ -f "$ROOT/routing/routes.json" ]] || fail "routing/routes.json ausente"
[[ -x "$ROOT/routing/install_hml_center.sh" ]] || fail "routing/install_hml_center.sh deve ser executavel"

docker inspect vitrine_nginx >/dev/null 2>&1 || fail "container vitrine_nginx nao encontrado"
docker network inspect vitrine_net >/dev/null 2>&1 || fail "rede vitrine_net nao encontrada"

python3 "$ROOT/routing/validate_routes.py" "$ROOT/routing/routes.json"
python3 "$ROOT/routing/dns_preflight.py" --expected-ip "$EXPECTED_IP" --registry "$ROOT/routing/routes.json" \
  --route-id vitrine-hml-center --route-id cursos-ia-hml

HML_CENTER_ENV_FILE="$SECRETS_FILE" "$ROOT/routing/install_hml_center.sh" "$ROOT"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="/srv/vitrine/backups/routing/$stamp"
mkdir -p "$backup_root"
mkdir -p "$NGINX_CONF_ROOT" "$NGINX_HTML_ROOT" "$SSL_ROOT"

rollback() {
  rc=$?
  info "falha detectada; iniciando rollback"
  for route_id in "${ROUTES[@]}"; do
    target="$NGINX_CONF_ROOT/$route_id.conf"
    if [[ -f "$backup_root/$route_id.conf" ]]; then
      cp -a "$backup_root/$route_id.conf" "$target"
    else
      rm -f "$target"
    fi
  done
  docker exec vitrine_nginx nginx -t >/dev/null 2>&1 || true
  docker exec vitrine_nginx nginx -s reload >/dev/null 2>&1 || true
  exit "$rc"
}
trap rollback ERR

for route_id in "${ROUTES[@]}"; do
  target="$NGINX_CONF_ROOT/$route_id.conf"
  [[ -f "$target" ]] && cp -a "$target" "$backup_root/$route_id.conf"
done

http_stage="$(mktemp -d)"
https_stage="$(mktemp -d)"
trap 'rm -rf "$http_stage" "$https_stage"' EXIT

for route_id in "${ROUTES[@]}"; do
  python3 "$ROOT/routing/generate_nginx.py" "$ROOT/routing/routes.json" --phase http --route-id "$route_id" --output "$http_stage"
  cp "$http_stage/$route_id.conf" "$NGINX_CONF_ROOT/$route_id.conf"
done

docker exec vitrine_nginx nginx -t
docker exec vitrine_nginx nginx -s reload

host_for_route() {
  python3 - "$ROOT/routing/routes.json" "$1" <<'PY'
import json, sys
path, route_id = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding='utf-8'))
for route in data['routes']:
    if route['id'] == route_id:
        print(route['hostname'])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

for route_id in "${ROUTES[@]}"; do
  host="$(host_for_route "$route_id")"
  info "emitindo/renovando certificado para $host"
  docker run --rm \
    -v "$SSL_ROOT:/etc/letsencrypt" \
    -v "$NGINX_HTML_ROOT:/usr/share/nginx/html" \
    "$CERTBOT_IMAGE" certonly \
    --webroot --webroot-path /usr/share/nginx/html \
    --domain "$host" --email "$CERTBOT_EMAIL" \
    --agree-tos --non-interactive --no-eff-email --keep-until-expiring

  [[ -s "$SSL_ROOT/live/$host/fullchain.pem" ]] || fail "fullchain ausente para $host"
  [[ -s "$SSL_ROOT/live/$host/privkey.pem" ]] || fail "privkey ausente para $host"

  python3 "$ROOT/routing/generate_nginx.py" "$ROOT/routing/routes.json" --phase full --route-id "$route_id" --output "$https_stage"
  cp "$https_stage/$route_id.conf" "$NGINX_CONF_ROOT/$route_id.conf"
done

docker exec vitrine_nginx nginx -t
docker exec vitrine_nginx nginx -s reload

python3 - <<'PY'
import ssl, urllib.request
checks = [
    ('https://hml.vitrineiapro.com.br/health', 200),
    ('https://cursos.hml.vitrineiapro.com.br/health.php', 200),
]
ctx = ssl.create_default_context()
for url, expected in checks:
    with urllib.request.urlopen(url, timeout=20, context=ctx) as response:
        if response.status != expected:
            raise SystemExit(f'{url}: status {response.status}, esperado {expected}')
        print(f'OK {url} -> {response.status}')
PY

trap - ERR
info "HML publicada com sucesso"
info "backup de rollback: $backup_root"

#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${1:-$(pwd)}"
TARGET_ROOT="${VITRINE_ROUTING_ROOT:-/srv/vitrine/routing}"
SECRETS_FILE="${HML_CENTER_ENV_FILE:-/srv/vitrine/secrets/hml-center.env}"
NETWORK="vitrine_net"

fail() { echo "ERRO: $*" >&2; exit 1; }
info() { echo "[hml-center] $*"; }

[[ -f "$SOURCE_ROOT/routing/routes.json" ]] || fail "routing/routes.json nao encontrado em $SOURCE_ROOT"
[[ -f "$SOURCE_ROOT/routing/hml-center/docker-compose.yml" ]] || fail "docker-compose.yml da Central HML nao encontrado"
[[ -f "$SOURCE_ROOT/routing/hml-center/Dockerfile" ]] || fail "Dockerfile da Central HML nao encontrado"
[[ -f "$SECRETS_FILE" ]] || fail "arquivo de credenciais ausente: $SECRETS_FILE"

grep -Eq '^HML_CENTER_USER=.+' "$SECRETS_FILE" || fail "HML_CENTER_USER ausente no arquivo de credenciais"
grep -Eq '^HML_CENTER_PASSWORD=.+' "$SECRETS_FILE" || fail "HML_CENTER_PASSWORD ausente no arquivo de credenciais"

if command -v stat >/dev/null 2>&1; then
  perms="$(stat -c '%a' "$SECRETS_FILE" 2>/dev/null || true)"
  if [[ -n "$perms" && "$perms" -gt 600 ]]; then
    fail "permissoes inseguras em $SECRETS_FILE ($perms); use chmod 600"
  fi
fi

docker network inspect "$NETWORK" >/dev/null 2>&1 || fail "rede Docker externa $NETWORK nao existe"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -d "$TARGET_ROOT/hml-center" || -f "$TARGET_ROOT/routes.json" ]]; then
  backup="$TARGET_ROOT/backups/$stamp"
  install -d -m 0750 "$backup"
  [[ -f "$TARGET_ROOT/routes.json" ]] && cp -a "$TARGET_ROOT/routes.json" "$backup/routes.json"
  [[ -d "$TARGET_ROOT/hml-center" ]] && cp -a "$TARGET_ROOT/hml-center" "$backup/hml-center"
  info "backup criado em $backup"
fi

install -d -m 0750 "$TARGET_ROOT/hml-center"
install -m 0640 "$SOURCE_ROOT/routing/routes.json" "$TARGET_ROOT/routes.json"
cp -a "$SOURCE_ROOT/routing/hml-center/." "$TARGET_ROOT/hml-center/"

python3 "$SOURCE_ROOT/routing/validate_routes.py" "$TARGET_ROOT/routes.json"

docker compose \
  --env-file "$SECRETS_FILE" \
  -f "$TARGET_ROOT/hml-center/docker-compose.yml" \
  up -d --build

container_id="$(docker compose --env-file "$SECRETS_FILE" -f "$TARGET_ROOT/hml-center/docker-compose.yml" ps -q hml-center)"
[[ -n "$container_id" ]] || fail "container da Central HML nao foi criado"

health="$(docker exec "$container_id" python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5).read().decode())" 2>/dev/null || true)"
[[ -n "$health" ]] || fail "healthcheck interno da Central HML falhou"

info "Central HML instalada e saudavel"
printf '%s\n' "$health"

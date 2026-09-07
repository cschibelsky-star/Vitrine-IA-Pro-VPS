#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
LOG_ROOT="${LOG_ROOT:-/var/log/vitrine-backup}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"
REMOTE="${RCLONE_REMOTE:-vitrine-drive}"
PREFIX="${RCLONE_PREFIX:-Vitrine-IA-Pro-Backups}"
RCLONE_CONFIG="${RCLONE_CONFIG:-/config/rclone/rclone.conf}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_ROOT" "$LOG_ROOT"
LOG_FILE="$LOG_ROOT/backup-agent.log"

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$LOG_FILE"
}

container_running() {
  docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -qx true
}

backup_mariadb() {
  local project="$1" container="$2" database="$3" user_env="$4" pass_env="$5"
  local ts dir tmp out hash
  ts="$(date -u +'%Y%m%dT%H%M%SZ')"
  dir="$BACKUP_ROOT/$project/database"
  mkdir -p "$dir"
  tmp="$dir/.${database}-${ts}.sql.tmp"
  out="$dir/${database}-${ts}.sql"

  if ! container_running "$container"; then
    log "WARN project=$project status=container_unavailable container=$container"
    return 0
  fi

  if ! docker exec "$container" sh -lc "test -n \"\${$user_env:-}\" && test -n \"\${$pass_env:-}\"" >/dev/null 2>&1; then
    log "WARN project=$project status=db_credentials_unavailable container=$container"
    return 0
  fi

  if docker exec "$container" sh -lc "mariadb-dump --single-transaction --quick --routines --events --triggers -u\"\${$user_env}\" -p\"\${$pass_env}\" \"$database\"" > "$tmp"; then
    if [ -s "$tmp" ]; then
      mv "$tmp" "$out"
      hash="$(sha256sum "$out" | awk '{print $1}')"
      printf '%s  %s\n' "$hash" "$(basename "$out")" > "$out.sha256"
      log "OK project=$project database=$database bytes=$(wc -c < "$out") sha256=$hash"
    else
      rm -f "$tmp"
      log "ERROR project=$project status=empty_dump database=$database"
    fi
  else
    rm -f "$tmp"
    log "ERROR project=$project status=dump_failed database=$database"
  fi
}

sync_drive() {
  if [ ! -s "$RCLONE_CONFIG" ]; then
    log "WARN status=drive_not_configured config=$RCLONE_CONFIG"
    return 0
  fi
  if ! rclone listremotes --config "$RCLONE_CONFIG" | grep -qx "${REMOTE}:"; then
    log "WARN status=drive_remote_missing remote=$REMOTE"
    return 0
  fi
  if rclone copy "$BACKUP_ROOT" "${REMOTE}:${PREFIX}" --config "$RCLONE_CONFIG" --create-empty-src-dirs --checksum --transfers 2 --checkers 4 --log-file "$LOG_ROOT/rclone.log" --log-level INFO; then
    log "OK status=drive_synced remote=${REMOTE}:${PREFIX}"
  else
    log "ERROR status=drive_sync_failed remote=${REMOTE}:${PREFIX}"
  fi
}

run_cycle() {
  log "START cycle"
  backup_mariadb "core" "vitrine_core_db_hml" "vitrine_core_hml" "MARIADB_USER" "MARIADB_PASSWORD"
  backup_mariadb "factory" "vitrine_factory_hml_db" "vitrine_factory_hml" "MARIADB_USER" "MARIADB_PASSWORD"

  # Social Enterprise is intentionally attempted only if its expected DB container exists.
  backup_mariadb "social-enterprise" "vitrine_mariadb" "vitrine_social" "MARIADB_USER" "MARIADB_PASSWORD"

  find "$BACKUP_ROOT" -type f -mtime "+$RETENTION_DAYS" -delete || true
  sync_drive
  log "END cycle"
}

trap 'log "STOP signal_received"; exit 0' TERM INT

while true; do
  run_cycle
  sleep "$INTERVAL" & wait $!
done

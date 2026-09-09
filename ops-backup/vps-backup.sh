#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-86400}"
SOURCE_ROOT="${SOURCE_ROOT:-/source}"

mkdir -p "$BACKUP_ROOT"
umask 077

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="vitrine-vps-${stamp}"
  partial="${BACKUP_ROOT}/${base}.tar.gz.partial"
  archive="${BACKUP_ROOT}/${base}.tar.gz"
  checksum="${archive}.sha256"

  echo "[$(date -u +%FT%TZ)] backup_start archive=${archive}"

  rm -f "$partial"

  if ! tar -czf "$partial" \
    -C "$SOURCE_ROOT" \
    --exclude='./proc' \
    --exclude='./sys' \
    --exclude='./dev' \
    --exclude='./run' \
    --exclude='./tmp' \
    --exclude='./mnt' \
    --exclude='./media' \
    --exclude='./var/lib/docker' \
    --exclude='./srv/backups/vps' \
    .; then
    rm -f "$partial"
    echo "[$(date -u +%FT%TZ)] backup_failed stage=archive" >&2
    return 1
  fi

  if [ ! -s "$partial" ]; then
    rm -f "$partial"
    echo "[$(date -u +%FT%TZ)] backup_failed stage=empty_archive" >&2
    return 1
  fi

  mv "$partial" "$archive"

  if ! sha256sum "$archive" > "$checksum"; then
    rm -f "$checksum"
    echo "[$(date -u +%FT%TZ)] backup_failed stage=checksum" >&2
    return 1
  fi

  find "$BACKUP_ROOT" -maxdepth 1 -type f \
    \( -name 'vitrine-vps-*.tar.gz' -o -name 'vitrine-vps-*.tar.gz.sha256' -o -name 'vitrine-vps-*.partial' \) \
    -mtime "+${RETENTION_DAYS}" -delete

  size="$(wc -c < "$archive" | tr -d ' ')"
  echo "[$(date -u +%FT%TZ)] backup_ok archive=${archive} bytes=${size} checksum=${checksum}"
}

if [ "${RUN_ONCE:-0}" = "1" ]; then
  run_backup
  exit 0
fi

while true; do
  if ! run_backup; then
    echo "[$(date -u +%FT%TZ)] backup_cycle_failed" >&2
  fi
  sleep "$INTERVAL_SECONDS"
done

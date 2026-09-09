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

  tar \
    --warning=no-file-changed \
    --ignore-failed-read \
    -czf "$partial" \
    -C "$SOURCE_ROOT" .

  test -s "$partial"
  mv "$partial" "$archive"
  sha256sum "$archive" > "$checksum"

  find "$BACKUP_ROOT" -maxdepth 1 -type f \
    \( -name 'vitrine-vps-*.tar.gz' -o -name 'vitrine-vps-*.tar.gz.sha256' -o -name 'vitrine-vps-*.partial' \) \
    -mtime "+${RETENTION_DAYS}" -delete

  size="$(wc -c < "$archive" | tr -d ' ')"
  echo "[$(date -u +%FT%TZ)] backup_ok archive=${archive} bytes=${size}"
}

if [ "${RUN_ONCE:-0}" = "1" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup || echo "[$(date -u +%FT%TZ)] backup_failed" >&2
  sleep "$INTERVAL_SECONDS"
done

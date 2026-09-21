#!/bin/sh
set -eu

STAGING_ROOT="${STAGING_ROOT:-/staging}"
REMOTE_ROOT="${REMOTE_ROOT:-vitrine-drive-crypt:Vitrine-IA-Pro/Backups/VPS}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-86400}"
SOURCE_ROOT="${SOURCE_ROOT:-/source}"
ARCHIVE_NAME="vps-latest.tar.gz"
CHECKSUM_NAME="${ARCHIVE_NAME}.sha256"

mkdir -p "$STAGING_ROOT"
umask 077

run_backup() {
  archive="$STAGING_ROOT/$ARCHIVE_NAME"
  partial="$STAGING_ROOT/$ARCHIVE_NAME.partial"
  checksum="$STAGING_ROOT/$CHECKSUM_NAME"

  echo "[$(date -u +%FT%TZ)] backup_start remote=$REMOTE_ROOT/$ARCHIVE_NAME"

  rm -f "$partial" "$archive" "$checksum"

  if ! tar -czf "$partial" -C "$SOURCE_ROOT" \
    --exclude='srv/backups' \
    --exclude='srv/vitrine/backups' \
    --exclude='var/lib/docker' \
    --exclude='var/lib/containerd' \
    srv/projects \
    srv/tvsumare \
    srv/connectors \
    opt/n8n-traefik \
    srv/vitrine/docker/nginx/conf.d \
    srv/vitrine/docker/nginx/html \
    srv/vitrine/ssl \
    etc; then
    rm -f "$partial"
    echo "[$(date -u +%FT%TZ)] backup_failed stage=archive" >&2
    return 1
  fi

  [ -s "$partial" ] || {
    rm -f "$partial"
    echo "[$(date -u +%FT%TZ)] backup_failed stage=empty_archive" >&2
    return 1
  }

  mv "$partial" "$archive"
  sha256sum "$archive" | sed "s|$STAGING_ROOT/||" > "$checksum"

  if ! rclone copyto "$archive" "$REMOTE_ROOT/$ARCHIVE_NAME.uploading"; then
    echo "[$(date -u +%FT%TZ)] backup_failed stage=upload_archive" >&2
    return 1
  fi

  if ! rclone moveto "$REMOTE_ROOT/$ARCHIVE_NAME.uploading" "$REMOTE_ROOT/$ARCHIVE_NAME"; then
    echo "[$(date -u +%FT%TZ)] backup_failed stage=publish_archive" >&2
    return 1
  fi

  if ! rclone copyto "$checksum" "$REMOTE_ROOT/$CHECKSUM_NAME"; then
    echo "[$(date -u +%FT%TZ)] backup_failed stage=upload_checksum" >&2
    return 1
  fi

  remote_size="$(rclone size "$REMOTE_ROOT/$ARCHIVE_NAME" --json | tr -d '\n' || true)"
  echo "[$(date -u +%FT%TZ)] backup_ok remote=$REMOTE_ROOT/$ARCHIVE_NAME verify=$remote_size"

  rm -f "$archive" "$checksum"
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

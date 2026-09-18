#!/bin/sh
set -eu

ROOT="${1:-/opt/n8n-traefik/workflows}"
MAIN_CONTAINER="${N8N_CONTAINER:-n8n-main}"

for file in "$ROOT"/*.json; do
  [ -f "$file" ] || continue
  base="$(basename "$file")"
  tmp="/tmp/$base"
  docker cp "$file" "$MAIN_CONTAINER:$tmp"
  docker exec "$MAIN_CONTAINER" n8n import:workflow --input="$tmp"
  docker exec "$MAIN_CONTAINER" rm -f "$tmp"
done

docker exec "$MAIN_CONTAINER" n8n list:workflow

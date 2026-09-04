#!/bin/sh
set -eu

CONF="/nginx-conf/mcp-v5.conf"
BACKUP="/nginx-conf/mcp-v5.conf.break-glass-backup"
TMP="/tmp/mcp-v5.conf.new"
MARKER="location = /break-glass/health"

if [ ! -f "$CONF" ]; then
  echo "error: mcp-v5.conf not found" >&2
  exit 1
fi

if grep -q "$MARKER" "$CONF"; then
  echo "break-glass health route already present"
  docker exec vitrine_nginx nginx -t
  docker exec vitrine_nginx nginx -s reload
  exit 0
fi

cp "$CONF" "$BACKUP"

awk '
  BEGIN { inserted=0 }
  /^[[:space:]]*location[[:space:]]*=[[:space:]]*\/mcp[[:space:]]*\{/ && inserted==0 {
    print "    location = /break-glass/health {"
    print "        auth_basic off;"
    print "        limit_except GET { deny all; }"
    print "        proxy_pass http://vitrine_break_glass_api:8099/health;"
    print "        proxy_http_version 1.1;"
    print "        proxy_set_header Host $host;"
    print "        proxy_set_header X-Real-IP $remote_addr;"
    print "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"
    print "        proxy_set_header X-Forwarded-Proto $scheme;"
    print "        add_header Cache-Control \"no-store\" always;"
    print "    }"
    print ""
    inserted=1
  }
  { print }
  END { if (inserted==0) exit 42 }
' "$CONF" > "$TMP" || {
  cp "$BACKUP" "$CONF"
  echo "error: insertion point not found" >&2
  exit 1
}

cat "$TMP" > "$CONF"

if ! docker exec vitrine_nginx nginx -t >/tmp/nginx-test.out 2>&1; then
  cp "$BACKUP" "$CONF"
  docker exec vitrine_nginx nginx -t >/dev/null 2>&1 || true
  cat /tmp/nginx-test.out >&2
  echo "error: nginx validation failed; configuration restored" >&2
  exit 1
fi

docker exec vitrine_nginx nginx -s reload
rm -f "$BACKUP"
echo "break-glass health route published and nginx reloaded"

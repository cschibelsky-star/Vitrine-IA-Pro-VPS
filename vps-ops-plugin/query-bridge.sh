#!/bin/sh
set -u

STATUS=/bootstrap/query-status.txt
QUERY=/bootstrap/query.json
RESULT=/bootstrap/query-result.txt
URL=http://vitrine_ops_api_hml:8080/projects/shared/read

echo BRIDGE_STARTED > "$STATUS"

while true; do
  if [ -s "$QUERY" ]; then
    echo PROCESSING_QUERY > "$STATUS"
    code="$(curl --max-time 15 -sS -o "$RESULT" -w '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer ${OPS_BROKER_TOKEN:-}" \
      -H 'Content-Type: application/json' \
      --data-binary "@$QUERY" \
      "$URL" 2>/bootstrap/query-error.txt || true)"
    echo "HTTP_CODE=$code" > "$STATUS"
  fi
  sleep 3
done

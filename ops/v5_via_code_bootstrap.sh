#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
LIVE_ROOT=/srv/projects/vitrine-vps-mcp-v59-integration/repository
CAN_ROOT=/srv/projects/v5-via-code-candidate-hml/repository
LIVE_COMPOSE="$LIVE_ROOT/docker-compose.connector-v5.yml"
OLD_IMAGE=sha256:c7789a50fa253f2450848ee6407dfffed8dd576048672c96c2023683a1be372b
NEW_TAG=vitrine-v5-via-code-candidate:20261102
LIVE_NAME=vitrine_mcp_v5
CAN_NAME=vitrine_v5_via_code_candidate
PROJ=vitrine-mcp-v5-v59
TOOL=project_roteia_via_code_pilot_execute

[[ $EUID -eq 0 ]] || { echo 'BLOCKED: requires root'; exit 2; }
for cmd in docker git python3 flock timeout; do command -v "$cmd" >/dev/null || exit 2; done
exec 9>/run/lock/v5-via-code-bootstrap.lock
flock -n 9 || { echo 'BLOCKED: already running'; exit 2; }
[[ -f $LIVE_COMPOSE && -f $CAN_ROOT/ops/v5_via_code_bootstrap.sh ]] || exit 2
[[ $(git -C "$CAN_ROOT" branch --show-current) == feature/connector-via-code-pilot-mcp-20261102 ]] || exit 2
[[ -z $(git -C "$CAN_ROOT" status --porcelain) ]] || exit 2
[[ -z $(git -C "$LIVE_ROOT" status --porcelain) ]] || exit 2
[[ $(docker image inspect "$OLD_IMAGE" --format '{{.Id}}') == "$OLD_IMAGE" ]] || exit 2
[[ $(docker inspect "$LIVE_NAME" --format '{{.Image}}') == "$OLD_IMAGE" ]] || { echo 'BLOCKED: live image changed'; exit 2; }
[[ $(docker inspect "$LIVE_NAME" --format '{{.State.Health.Status}}') == healthy ]] || exit 2
[[ $(docker inspect "$CAN_NAME" --format '{{.State.Health.Status}}') == healthy ]] || exit 2
NEW_IMAGE=$(docker image inspect "$NEW_TAG" --format '{{.Id}}')
[[ -n $NEW_IMAGE && $NEW_IMAGE != "$OLD_IMAGE" ]] || exit 2
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
STATE_DIR="/srv/vitrine/backups/v5-via-code-$STAMP"
mkdir -m 700 "$STATE_DIR"
ROLLBACK_TAG="vitrine-v5-rollback:$STAMP"
docker image tag "$OLD_IMAGE" "$ROLLBACK_TAG"
[[ $(docker image inspect "$ROLLBACK_TAG" --format '{{.Id}}') == "$OLD_IMAGE" ]] || exit 2
printf 'baseline=%s\ncandidate=%s\n' "$OLD_IMAGE" "$NEW_IMAGE" > "$STATE_DIR/images.txt"
cat > "$STATE_DIR/upgrade.yml" <<'YAML'
services:
  connector_v5:
    image: vitrine-v5-via-code-candidate:20261102
    command: ["python", "/app/via_code_overlay_entrypoint.py"]
YAML
cat > "$STATE_DIR/rollback.yml" <<YAML
services:
  connector_v5:
    image: $ROLLBACK_TAG
    command: ["python", "/app/main_ext.py"]
YAML
compose_up=(docker compose -p "$PROJ" -f "$LIVE_COMPOSE" -f "$STATE_DIR/upgrade.yml")
compose_back=(docker compose -p "$PROJ" -f "$LIVE_COMPOSE" -f "$STATE_DIR/rollback.yml")
"\${compose_up[@]}" config -q >/dev/null
"\${compose_back[@]}" config -q >/dev/null
catalog() { timeout 25s docker exec "$CAN_NAME" python /app/via_code_mcp_catalog.py "$1"; }
catalog http://vitrine_mcp_v5:8000/mcp > "$STATE_DIR/tools.before.json"
catalog http://127.0.0.1:8000/mcp > "$STATE_DIR/tools.candidate.json"
python3 - "$STATE_DIR" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
a=json.loads((p/'tools.before.json').read_text())
b=json.loads((p/'tools.candidate.json').read_text())
assert 'project_roteia_via_code_pilot_execute' not in a
assert b.count('project_roteia_via_code_pilot_execute') == 1
assert set(a).issubset(b), 'old MCP tools missing in candidate'
print('PREFLIGHT OK: current MCP tools preserved by candidate')
PY
if [[ \${1:-} != EXECUTAR_V5_VIA_CODE ]]; then
  echo "PREFLIGHT ONLY; no deployment; artifacts=$STATE_DIR"
  exit 0
fi
switched=0
on_exit() {
  result=$?
  trap - EXIT
  if [[ $switched == 1 && $result != 0 ]]; then
    echo 'VALIDATION FAILED; starting automatic rollback'
    if "\${compose_back[@]}" up -d --no-build --no-deps connector_v5; then
      for i in $(seq 1 25); do
        if [[ $(docker inspect "$LIVE_NAME" --format '{{.Image}}' 2>/dev/null || :) == "$OLD_IMAGE" && $(docker inspect "$LIVE_NAME" --format '{{.State.Health.Status}}' 2>/dev/null || :) == healthy ]]; then
          echo 'ROLLBACK HEALTHY'; exit "$result"
        fi
        sleep 2
      done
    fi
    echo "CRITICAL: rollback not verified; artifacts=$STATE_DIR"
  fi
  exit "$result"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
switched=1
"\${compose_up[@]}" up -d --no-build --no-deps connector_v5
healthy=0
for i in $(seq 1 25); do
  if [[ $(docker inspect "$LIVE_NAME" --format '{{.Image}}' 2>/dev/null || :) == "$NEW_IMAGE" && $(docker inspect "$LIVE_NAME" --format '{{.State.Health.Status}}' 2>/dev/null || :) == healthy ]]; then
    healthy=1; break
  fi
  sleep 2
done
[[ $healthy == 1 ]] || { echo 'BLOCKED: new image not healthy'; exit 1; }
catalog http://vitrine_mcp_v5:8000/mcp > "$STATE_DIR/tools.after.json"
python3 - "$STATE_DIR" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
a=json.loads((p/'tools.before.json').read_text())
b=json.loads((p/'tools.after.json').read_text())
assert set(a).issubset(b), 'regression in MCP tool catalog'
assert b.count('project_roteia_via_code_pilot_execute') == 1
print('SUCCESS: new tool and all prior MCP tools verified')
PY
switched=0
echo "SUCCESS; new image=$NEW_IMAGE; rollback image=$ROLLBACK_TAG; artifacts=$STATE_DIR"

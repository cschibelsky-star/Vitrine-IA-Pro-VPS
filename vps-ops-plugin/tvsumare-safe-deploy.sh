#!/bin/sh

LOG=/bootstrap/tvsumare-safe-deploy.txt
exec >"$LOG" 2>&1

echo 'TVSUMARE_SAFE_DEPLOY=START'
date -u '+AT=%Y-%m-%dT%H:%M:%SZ'

cd /srv/tvsumare/repository || {
  echo 'ERROR=repository_unavailable'
  exit 10
}

old_id=$(docker inspect -f '{{.Id}}' tvsumare_web 2>/dev/null) || {
  echo 'ERROR=existing_container_not_found'
  exit 11
}
old_image=$(docker inspect -f '{{.Image}}' tvsumare_web 2>/dev/null) || {
  echo 'ERROR=existing_image_unknown'
  exit 12
}
old_health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' tvsumare_web 2>/dev/null || true)
new_image=$(docker image inspect repository-web:latest -f '{{.Id}}' 2>/dev/null) || {
  echo 'ERROR=candidate_image_not_found'
  exit 13
}

echo "OLD_CONTAINER_ID=$old_id"
echo "OLD_IMAGE_ID=$old_image"
echo "OLD_HEALTH=$old_health"
echo "NEW_IMAGE_ID=$new_image"

if [ "$old_image" = "$new_image" ]; then
  echo 'RESULT=already_on_candidate_image'
  echo 'TVSUMARE_SAFE_DEPLOY=END'
  exit 0
fi

if [ "$old_health" != 'healthy' ]; then
  echo 'ERROR=existing_container_not_healthy'
  exit 14
fi

stamp=$(date -u '+%Y%m%d-%H%M%S')
rollback_tag="repository-web:rollback-$stamp"
candidate_tag="repository-web:candidate-$stamp"

if docker image inspect "$old_image" >/dev/null 2>&1; then
  docker image tag "$old_image" "$rollback_tag" || {
    echo 'ERROR=rollback_tag_failed'
    exit 15
  }
  echo 'ROLLBACK_SOURCE=existing_image'
else
  echo 'ROLLBACK_SOURCE=container_snapshot'
  docker commit --pause=false \
    --change 'ENV OPENAI_API_KEY=' \
    --change 'ENV GEMINI_API_KEY=' \
    --change 'ENV HEYGEN_API_KEY=' \
    --change 'ENV YOUTUBE_CLIENT_SECRET=' \
    --change 'ENV TVSUMARE_ADMIN_PASS_HASH=' \
    --change 'ENV SITE_FACTORY_TOKEN=' \
    tvsumare_web "$rollback_tag" >/tmp/tvsumare-rollback-image-id.txt 2>/tmp/tvsumare-rollback-commit.err || {
      echo 'ERROR=rollback_snapshot_failed'
      cat /tmp/tvsumare-rollback-commit.err 2>/dev/null || true
      exit 16
    }

  rollback_env=$(docker image inspect "$rollback_tag" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null) || {
    echo 'ERROR=rollback_snapshot_inspect_failed'
    exit 17
  }
  for key in OPENAI_API_KEY GEMINI_API_KEY HEYGEN_API_KEY YOUTUBE_CLIENT_SECRET TVSUMARE_ADMIN_PASS_HASH SITE_FACTORY_TOKEN; do
    value=$(printf '%s\n' "$rollback_env" | awk -F= -v k="$key" '$1==k{v=substr($0,length(k)+2)} END{print v}')
    if [ -n "$value" ]; then
      echo "ERROR=rollback_sensitive_env_not_scrubbed KEY=$key"
      exit 18
    fi
  done
  echo 'ROLLBACK_SENSITIVE_ENV_SCRUBBED=SIM'
fi

rollback_image=$(docker image inspect "$rollback_tag" -f '{{.Id}}' 2>/dev/null) || {
  echo 'ERROR=rollback_image_unavailable'
  exit 19
}
docker image tag "$new_image" "$candidate_tag" || {
  echo 'ERROR=candidate_tag_failed'
  exit 20
}

echo "ROLLBACK_TAG=$rollback_tag"
echo "ROLLBACK_IMAGE_ID=$rollback_image"
echo "CANDIDATE_TAG=$candidate_tag"

echo 'DEPLOY_ACTION=compose_force_recreate_web'
docker compose -p repository -f docker-compose.vps.yml up -d --force-recreate web
up_rc=$?
echo "DEPLOY_EXIT_CODE=$up_rc"

check_candidate_health() {
  expected="$1"
  i=0
  while [ "$i" -lt 24 ]; do
    current_status=$(docker inspect -f '{{.State.Status}}' tvsumare_web 2>/dev/null || echo missing)
    current_health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' tvsumare_web 2>/dev/null || echo missing)
    current_image=$(docker inspect -f '{{.Image}}' tvsumare_web 2>/dev/null || echo missing)
    echo "CHECK=$i STATUS=$current_status HEALTH=$current_health IMAGE=$current_image"
    if [ "$current_status" = 'running' ] && [ "$current_health" = 'healthy' ] && [ "$current_image" = "$expected" ]; then
      return 0
    fi
    if [ "$current_status" = 'dead' ] || [ "$current_status" = 'exited' ]; then
      return 1
    fi
    i=$((i + 1))
    sleep 5
  done
  return 1
}

if [ "$up_rc" -eq 0 ] && check_candidate_health "$new_image"; then
  echo 'RESULT=deploy_success'
  echo 'ROLLBACK_AVAILABLE=SIM'
  echo 'TVSUMARE_SAFE_DEPLOY=END'
  exit 0
fi

echo 'ROLLBACK_ACTION=restore_previous_snapshot'
docker image tag "$rollback_tag" repository-web:latest || {
  echo 'ROLLBACK_RESULT=retag_failed'
  exit 21
}
docker compose -p repository -f docker-compose.vps.yml up -d --force-recreate web
rollback_rc=$?
echo "ROLLBACK_DEPLOY_EXIT_CODE=$rollback_rc"

if [ "$rollback_rc" -eq 0 ] && check_candidate_health "$rollback_image"; then
  echo 'RESULT=deploy_failed_rollback_success'
  echo 'TVSUMARE_SAFE_DEPLOY=END'
  exit 22
fi

echo 'RESULT=deploy_failed_rollback_failed'
echo 'TVSUMARE_SAFE_DEPLOY=END'
exit 23

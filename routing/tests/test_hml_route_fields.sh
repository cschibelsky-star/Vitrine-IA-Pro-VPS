#!/usr/bin/env bash
set -euo pipefail
# Regression coverage for route field decoding used by activate_single_hml_route.sh.
decode() {
  local field_line="$1"
  local -a route_fields
  mapfile -t route_fields <<< "$field_line"
  [[ "${#route_fields[@]}" -eq 7 ]] || return 1
  [[ "${route_fields[0]}" == "tv-hml.vitrineiapro.com.br" ]] || return 1
  [[ "${route_fields[1]}" == "tvsumare_web" ]] || return 1
  [[ "${route_fields[2]}" == "n8n-traefik_app_network" ]] || return 1
  [[ "${route_fields[3]}" == "le" ]] || return 1
  [[ "${route_fields[4]}" == "websecure" ]] || return 1
  [[ "${route_fields[5]}" == "80" ]] || return 1
  [[ "${route_fields[6]}" == 'Host(`tv-hml.vitrineiapro.com.br`)' ]] || return 1
}
good="$(printf '%s\n' tv-hml.vitrineiapro.com.br tvsumare_web n8n-traefik_app_network le websecure 80 'Host(`tv-hml.vitrineiapro.com.br`)')"
decode "$good"
if decode "$(printf '%s\n' tv-hml.vitrineiapro.com.br tvsumare_web n8n-traefik_app_network le websecure 80)"; then
  echo "FAIL: missing field accepted" >&2
  exit 1
fi
echo "PASS: HML route fields"

# Provider router namespace must not reuse an application router identifier.
script="$(dirname "$0")/../activate_single_hml_route.sh"
grep -Fq 'router_id="vitrine-provider-${route_id}"' "$script"
grep -Fq 'traefik.http.routers.${router_id}.rule' "$script"
grep -Fq 'traefik.http.services.${router_id}.loadbalancer.server.url' "$script"

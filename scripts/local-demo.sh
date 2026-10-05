#!/usr/bin/env bash

set -euo pipefail

repo_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
compose_file="$repo_dir/docker-compose.local.yml"
project_name="new-api-local-demo"

export NEW_API_LOCAL_PORT="${NEW_API_LOCAL_PORT:-3300}"
export NEW_API_LOCAL_MYSQL_PORT="${NEW_API_LOCAL_MYSQL_PORT:-33307}"
export LOCAL_DEMO_MYSQL_PASSWORD="${LOCAL_DEMO_MYSQL_PASSWORD:-LocalDemoMySQL123!}"
export LOCAL_DEMO_ROOT_PASSWORD="${LOCAL_DEMO_ROOT_PASSWORD:-LocalDemo123!}"
export LOCAL_DEMO_SESSION_SECRET="${LOCAL_DEMO_SESSION_SECRET:-local-demo-session-secret-only-for-loopback-2026}"

local_demo_root_username="demo-root"

compose=(docker compose --project-name "$project_name" --file "$compose_file")

usage() {
  cat <<'EOF'
Usage: ./scripts/local-demo.sh <command>

Commands:
  bootstrap       Start MySQL and Redis, seed demo data, and build the app
  seed            Idempotently refresh only the marked local demo records
  verify          Log in and verify the core local demo API pages
  status          Show the local demo containers
  down            Stop the local demo stack and preserve its data
  reset [--yes]   Delete only the local demo volumes, then bootstrap again
  help            Show this help

Environment:
  NEW_API_LOCAL_PORT           Host port (default: 3300)
  NEW_API_LOCAL_MYSQL_PORT     MySQL host port (default: 33307)
  LOCAL_DEMO_MYSQL_PASSWORD    MySQL root password (default: LocalDemoMySQL123!)
  LOCAL_DEMO_ROOT_PASSWORD     Demo root password (default: LocalDemo123!)
EOF
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required. Install and open Docker Desktop first." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but its service is unavailable. Open Docker Desktop and wait until it is running." >&2
    exit 1
  fi
}

wait_for_dependencies() {
  "${compose[@]}" up --detach --wait mysql redis
}

seed_demo_data() {
  "${compose[@]}" run --rm demo-seed
}

bootstrap() {
  require_docker
  wait_for_dependencies
  seed_demo_data
  "${compose[@]}" up --detach --build --wait new-api

  echo
  echo "Local demo is ready: http://127.0.0.1:${NEW_API_LOCAL_PORT}/sign-in"
  echo "Choose username and password login."
  echo "Username: ${local_demo_root_username}"
  echo "Password: ${LOCAL_DEMO_ROOT_PASSWORD} (local demo only)"
  echo "MySQL: root@127.0.0.1:${NEW_API_LOCAL_MYSQL_PORT}/new-api"
  echo "MySQL password: ${LOCAL_DEMO_MYSQL_PASSWORD} (local demo only)"
  echo "Run ./scripts/local-demo.sh verify to check the core pages."
}

seed() {
  require_docker
  wait_for_dependencies
  seed_demo_data

  if [[ -n $("${compose[@]}" ps --quiet new-api) ]]; then
    "${compose[@]}" restart new-api
  fi
  "${compose[@]}" up --detach --wait new-api
  echo "Local demo records were refreshed; non-demo records were left unchanged."
}

json_escape() {
  local value=$1
  value=${value//\/\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  printf '%s' "$value"
}

assert_response() {
  local label=$1
  local expected=$2
  local response_file=$3

  if ! grep -Fq '"success":true' "$response_file"; then
    echo "Verification failed at ${label}: API did not report success." >&2
    sed -n '1,5p' "$response_file" >&2
    return 1
  fi
  if [[ -n $expected ]] && ! grep -Fq "$expected" "$response_file"; then
    echo "Verification failed at ${label}: expected demo data was missing." >&2
    return 1
  fi
  echo "Verified: ${label}"
}

verify() {
  require_docker

  local base_url="http://127.0.0.1:${NEW_API_LOCAL_PORT}"
  local work_dir
  work_dir=$(mktemp -d)
  trap "rm -rf '$work_dir'" EXIT
  local cookie_file="$work_dir/cookies.txt"
  local response_file="$work_dir/response.json"
  local escaped_username escaped_password
  escaped_username=$(json_escape "$local_demo_root_username")
  escaped_password=$(json_escape "$LOCAL_DEMO_ROOT_PASSWORD")

  curl --fail --silent --show-error "$base_url/api/status" --output "$response_file"
  assert_response "application status" '"version"' "$response_file"

  curl --fail --silent --show-error "$base_url/api/setup" --output "$response_file"
  assert_response "setup status" '"status":true' "$response_file"

  curl --fail --silent --show-error \
    --cookie-jar "$cookie_file" \
    --header 'Content-Type: application/json' \
    --data "{\"username\":\"${escaped_username}\",\"password\":\"${escaped_password}\"}" \
    "$base_url/api/user/login" \
    --output "$response_file"
  assert_response "administrator login" "\"username\":\"${escaped_username}\"" "$response_file"

  local user_id
  user_id=$(grep -o '"id":[0-9][0-9]*' "$response_file" | head -n 1 | cut -d: -f2)
  if [[ ! $user_id =~ ^[0-9]+$ ]]; then
    echo "Verification failed at administrator login: user ID was missing." >&2
    return 1
  fi
  local auth_header=(--header "New-Api-User: ${user_id}")

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/user/self" --output "$response_file"
  assert_response "current user" "\"username\":\"${escaped_username}\"" "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/user/?p=1&page_size=20" --output "$response_file"
  assert_response "users" 'demo-user' "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/token/?p=1&page_size=20" --output "$response_file"
  assert_response "tokens" 'Demo unlimited token' "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/channel/?p=1&page_size=20" --output "$response_file"
  assert_response "channels" 'Local Demo OpenAI' "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/models/?p=1&page_size=20" --output "$response_file"
  assert_response "models" 'local-demo-gpt-4.1-mini' "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" "$base_url/api/log/?p=1&page_size=20" --output "$response_file"
  assert_response "logs" 'Local demo' "$response_file"

  local end_time start_time
  end_time=$(date +%s)
  start_time=$((end_time - 604800))
  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" \
    "$base_url/api/data/?start_timestamp=${start_time}&end_timestamp=${end_time}" \
    --output "$response_file"
  assert_response "dashboard data" 'local-demo-gpt-4.1-mini' "$response_file"

  curl --fail --silent --show-error --cookie "$cookie_file" "${auth_header[@]}" \
    "$base_url/api/data/flow?start_timestamp=${start_time}&end_timestamp=${end_time}" \
    --output "$response_file"
  assert_response "traffic statistics" 'local-demo-gpt-4.1-mini' "$response_file"

  echo "All local demo checks passed: ${base_url}/sign-in"
}

reset() {
  require_docker
  if [[ ${1:-} != "--yes" ]]; then
    printf 'Delete only the %s Docker volumes and rebuild the demo? [y/N] ' "$project_name"
    read -r answer
    case "$answer" in
      y|Y|yes|YES) ;;
      *) echo "Reset cancelled."; return 0 ;;
    esac
  fi

  "${compose[@]}" down --volumes --remove-orphans
  bootstrap
}

command=${1:-help}
case "$command" in
  bootstrap) bootstrap ;;
  seed) seed ;;
  verify) verify ;;
  status) require_docker; "${compose[@]}" ps ;;
  down) require_docker; "${compose[@]}" down ;;
  reset) reset "${2:-}" ;;
  help|-h|--help) usage ;;
  *)
    echo "Unsupported command: ${command}" >&2
    usage >&2
    exit 2
    ;;
esac

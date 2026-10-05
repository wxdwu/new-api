#!/usr/bin/env bash

set -euo pipefail

repo_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
script="$repo_dir/scripts/local-demo.sh"
compose_file="$repo_dir/docker-compose.local.yml"
dockerfile="$repo_dir/Dockerfile"

# The local demo must run the application and seeder against the same MySQL
# database, expose it only on loopback for inspection, and keep PostgreSQL out
# of the active stack. A PostgreSQL DSN or dependency here would split data
# between databases or make bootstrap wait for the wrong service.
compose_json=$(docker compose --project-name new-api-local-demo --file "$compose_file" config --format json)
python3 - "$compose_json" <<'PY'
import json
import sys

config = json.loads(sys.argv[1])
services = config["services"]
assert "mysql" in services
assert "postgres" not in services

mysql = services["mysql"]
assert mysql["image"] == "mysql:8.2"
assert mysql["environment"]["MYSQL_DATABASE"] == "new-api"
assert mysql["environment"]["MYSQL_ROOT_PASSWORD"] == "LocalDemoMySQL123!"
assert mysql["volumes"] == [{
    "type": "volume",
    "source": "local_mysql_data",
    "target": "/var/lib/mysql",
    "volume": {},
}]
assert mysql["ports"] == [{
    "mode": "ingress",
    "host_ip": "127.0.0.1",
    "target": 3306,
    "published": "33307",
    "protocol": "tcp",
}]

want_dsn = "root:LocalDemoMySQL123!@tcp(mysql:3306)/new-api?charset=utf8mb4&parseTime=True&loc=Local"
for service_name in ("new-api", "demo-seed"):
    service = services[service_name]
    assert service["environment"]["SQL_DSN"] == want_dsn
    assert service["depends_on"]["mysql"]["condition"] == "service_healthy"
PY

# A named volume cannot be mounted below a read-only bind mount. Keep runtime
# state outside /workspace so Docker can create the mount point.
! grep -Fq 'local_seed_data:/workspace/data' "$compose_file"
grep -Fq 'local_seed_data:/runtime/data' "$compose_file"

# The local build can override an unreachable Debian mirror without changing
# the production Dockerfile default.
grep -Fq 'ARG DEBIAN_MIRROR=deb.debian.org' "$dockerfile"
grep -Fq 'DEBIAN_MIRROR: mirrors.aliyun.com' "$compose_file"
grep -Fq 'ARG BUN_REGISTRY=https://registry.npmmirror.com' "$dockerfile"
grep -Fq 'bun install --filter ./classic --frozen-lockfile --linker=isolated --network-concurrency=8 --registry=${BUN_REGISTRY}' "$dockerfile"

# /api/status exposes GET, not HEAD. wget --spider would always receive 404.
! grep -Fq 'wget --quiet --spider' "$compose_file"
grep -Fq 'wget --quiet --output-document=/dev/null' "$compose_file"

help_output=$(bash "$script" help)
[[ "$help_output" == *"bootstrap"* ]]
[[ "$help_output" == *"verify"* ]]
[[ "$help_output" == *"reset"* ]]
grep -Fq 'New-Api-User:' "$script"
grep -Fq '$base_url/api/models/?p=1&page_size=20' "$script"
! grep -Fq 'LOCAL_DEMO_ROOT_USERNAME' "$script"
! grep -Fq 'LOCAL_DEMO_ROOT_USERNAME' "$compose_file"

set +e
unknown_output=$(bash "$script" unsupported-command 2>&1)
unknown_status=$?
set -e
[[ $unknown_status -eq 2 ]]
[[ "$unknown_output" == *"unsupported-command"* ]]

fake_bin=$(mktemp -d)
trap 'rm -rf "$fake_bin"' EXIT
printf '%s\n' '#!/bin/sh' 'if [ "$1" = "info" ]; then exit 1; fi' 'exit 0' >"$fake_bin/docker"
chmod +x "$fake_bin/docker"

set +e
daemon_output=$(PATH="$fake_bin:$PATH" bash "$script" status 2>&1)
daemon_status=$?
set -e
[[ $daemon_status -ne 0 ]]
[[ "$daemon_output" == *"Docker Desktop"* ]]

echo "local-demo shell behavior tests passed"

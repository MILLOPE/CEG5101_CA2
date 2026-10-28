#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$project_dir/results/logs" "$project_dir/results/data"
cd "$project_dir"
exec 9>"$project_dir/results/controller.lock"
if ! flock -n 9; then
    echo 'Controller is already running. Use its existing terminal.' >&2
    exit 1
fi
if ss -ltnH 'sport = :6653' | grep -q .; then
    echo 'Port 6653 is already in use. Stop the existing controller first.' >&2
    exit 1
fi
export EVENTLET_NO_GREENDNS=yes
"$project_dir/.venv/bin/ryu-manager" --observe-links --ofp-tcp-listen-port 6653 \
    "$project_dir/controller/path_controller.py" 2>&1 | tee "$project_dir/results/logs/controller.log"

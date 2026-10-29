#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "plot" ]]; then
    .venv/bin/python tools/plot_qn2.py examples/qn2/result.json --output figures/qn2-example
else
    run_name="$(date +%Y%m%d-%H%M%S)"
    mkdir -p results/qn2
    sudo python3 tests/check_qn2.py --output "results/qn2/$run_name"
    .venv/bin/python tools/plot_qn2.py "results/qn2/$run_name/result.json" \
        --output "figures/$run_name"
fi

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
output="results/qn4/$(date +%Y%m%d-%H%M%S)"
for scenario in h2-h3 h2-h6 h5-h6; do
    sudo python3 tests/check_qn4.py --case "$scenario" --output "$output/$scenario"
done
sudo chown -R "$(id -u):$(id -g)" "$output"
echo "Results and PNG figures: $output"

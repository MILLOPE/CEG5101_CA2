#!/usr/bin/env bash
# Install the tested Python 3.8 lab stack on Ubuntu 20.04.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(. /etc/os-release; echo "$VERSION_ID")" != "20.04" ]] || ! python3 -c 'import sys; assert sys.version_info[:2] == (3, 8)'; then
    echo 'Use Ubuntu 20.04 with Python 3.8 for this pinned lab environment.' >&2
    exit 1
fi
sudo apt-get update
sudo apt-get install -y git build-essential mininet openvswitch-switch iproute2 \
    python3-pip python3-venv python3-dev python3-tk xterm xvfb
sudo systemctl enable --now openvswitch-switch
# Ubuntu 20.04 may package Mininet for Python 2. Install a Python 3 copy.
mkdir -p .cache
if [[ ! -d .cache/mininet/.git ]]; then
    git clone https://github.com/mininet/mininet.git .cache/mininet
fi
git -C .cache/mininet checkout d7f399d7a1200b602bd6a95ae88bae1009664d4a
sudo python3 -m pip install --no-deps ./.cache/mininet
python3 -m venv .venv
.venv/bin/python -m pip install 'pip==24.0' 'setuptools==57.5.0' 'wheel==0.42.0'
# Older setuptools/eventlet are required by Ryu 4.34 on Python 3.8.
.venv/bin/python -m pip install --no-build-isolation -r requirements.txt
.venv/bin/python -m pip check
sudo python3 -c 'import tkinter, mininet; print("Mininet and Tk: OK")'
EVENTLET_NO_GREENDNS=yes .venv/bin/ryu-manager --version
printf '\nSetup complete. Start with: bash scripts/run_controller.sh\n'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 providers/gmat/adapter.py --scenario providers/gmat/scenarios/leo_demo.yaml --output /tmp/gmat-events.json "$@"


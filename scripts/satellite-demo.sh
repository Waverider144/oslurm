#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m oslurm.satellite_demo

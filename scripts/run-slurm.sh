#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SLURM_CONF="$PWD/.oslurm-state/slurm/etc/slurm.conf"
exec third_party/slurm-26.05.3/src/sinfo/sinfo "$@"

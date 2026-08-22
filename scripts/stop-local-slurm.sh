#!/usr/bin/env bash
set -euo pipefail

pkill -f 'third_party/slurm-26.05.3/src/slurmd/slurmd/slurmd' 2>/dev/null || true
pkill -f 'third_party/slurm-26.05.3/src/slurmctld/slurmctld' 2>/dev/null || true

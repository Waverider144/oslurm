#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ROOT="$PWD"
SLURM_ROOT="$ROOT/third_party/slurm-26.05.3"
STATE="$ROOT/.oslurm-state/slurm"
STEPD="$SLURM_ROOT/src/slurmd/slurmstepd/slurmstepd"

./scripts/setup-local-slurm.sh >/dev/null
./scripts/stop-local-slurm.sh >/dev/null || true
export HOSTALIASES="$STATE/etc/hostaliases"
export LD_PRELOAD="$STATE/hosts_alias_preload.so${LD_PRELOAD:+:$LD_PRELOAD}"

echo "Starting slurmctld..."
"$SLURM_ROOT/src/slurmctld/slurmctld" -c -f "$STATE/etc/slurm.conf" -i

for node in sat001 sat002 sat003 sat004; do
  echo "Starting slurmd $node..."
  "$SLURM_ROOT/src/slurmd/slurmd/slurmd" -f "$STATE/etc/slurm.conf" -N "$node" -d "$STEPD"
done

export SLURM_CONF="$STATE/etc/slurm.conf"
"$SLURM_ROOT/src/sinfo/sinfo" -Nel

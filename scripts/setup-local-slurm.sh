#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

ROOT="$PWD"
SLURM_ROOT="$ROOT/third_party/slurm-26.05.3"
STATE="$ROOT/.oslurm-state/slurm"
PLUG="$STATE/plugins"
HOSTNAME_SHORT="$(hostname -s)"

mkdir -p "$STATE"/{etc,state,logs,run,tmp} "$STATE/spool/sat001" "$STATE/spool/sat002" "$STATE/spool/sat003" "$STATE/spool/sat004" "$PLUG"

find "$SLURM_ROOT/src/plugins" -path '*/.libs/*.so' -type f | while read -r so; do
  ln -sf "$so" "$PLUG/$(basename "$so")"
done

cat > "$STATE/etc/slurm.conf" <<EOF
ClusterName=oslurm
SlurmctldHost=localhost
SlurmUser=$USER
SlurmdUser=$USER
SlurmctldPort=6817
SlurmdPort=6818
AuthType=auth/none
CredType=cred/none
CryptoType=crypto/openssl
PluginDir=$PLUG
StateSaveLocation=$STATE/state
SlurmdSpoolDir=$STATE/spool/%n
SlurmctldLogFile=$STATE/logs/slurmctld.log
SlurmdLogFile=$STATE/logs/slurmd-%n.log
SlurmctldPidFile=$STATE/run/slurmctld.pid
SlurmdPidFile=$STATE/run/slurmd-%n.pid
ReturnToService=2
SelectType=select/linear
ProctrackType=proctrack/linuxproc
TaskPlugin=task/none
SchedulerType=sched/backfill
SwitchType=switch/none
MpiDefault=none
InactiveLimit=0
KillWait=5
MinJobAge=60
SlurmctldTimeout=120
SlurmdTimeout=120
Waittime=0
NodeName=sat001 NodeHostName=sat001 NodeAddr=127.0.0.1 Port=6818 CPUs=12 Boards=1 SocketsPerBoard=1 CoresPerSocket=6 ThreadsPerCore=2 RealMemory=96049 State=UNKNOWN
NodeName=sat002 NodeHostName=sat002 NodeAddr=127.0.0.1 Port=6819 CPUs=12 Boards=1 SocketsPerBoard=1 CoresPerSocket=6 ThreadsPerCore=2 RealMemory=96049 State=UNKNOWN
NodeName=sat003 NodeHostName=sat003 NodeAddr=127.0.0.1 Port=6820 CPUs=12 Boards=1 SocketsPerBoard=1 CoresPerSocket=6 ThreadsPerCore=2 RealMemory=96049 State=UNKNOWN
NodeName=sat004 NodeHostName=sat004 NodeAddr=127.0.0.1 Port=6821 CPUs=12 Boards=1 SocketsPerBoard=1 CoresPerSocket=6 ThreadsPerCore=2 RealMemory=96049 State=UNKNOWN
PartitionName=debug Nodes=sat[001-004] Default=YES MaxTime=INFINITE State=UP
EOF

cat > "$STATE/etc/cgroup.conf" <<EOF
CgroupPlugin=disabled
EOF

cat > "$STATE/etc/hostaliases" <<EOF
sat001 127.0.0.1
sat002 127.0.0.1
sat003 127.0.0.1
sat004 127.0.0.1
EOF

gcc -shared -fPIC -ldl \
  "$ROOT/slurm/integration/hosts_alias_preload.c" \
  -o "$STATE/hosts_alias_preload.so"

echo "Wrote $STATE/etc/slurm.conf"
echo "Wrote $STATE/etc/hostaliases"
echo "Built $STATE/hosts_alias_preload.so"
echo "Start controller:"
echo "  $SLURM_ROOT/src/slurmctld/slurmctld -D -f $STATE/etc/slurm.conf -i -vv"
echo "Start satellite daemons:"
for node in sat001 sat002 sat003 sat004; do
  echo "  $SLURM_ROOT/src/slurmd/slurmd/slurmd -D -f $STATE/etc/slurm.conf -N $node -d $SLURM_ROOT/src/slurmd/slurmstepd/slurmstepd -vv"
done

# Multi-Constellation Networking

O-SLURM now has a small network layer for compute/communication co-scheduling.

The model separates four domains:

- `compute`: spacecraft that run jobs.
- `comm`: relay spacecraft and communication payloads.
- `access`: logical access links between mission users and relay resources.
- `ground`: mission control and ground stations.

The scheduler consumes `ContactWindow` records from GMAT-Comm or built-in scenario profiles. It creates `TransferIntent` objects for job input and output movement, plans direct or store-carry-forward routes, reserves network hops, then ranks compute candidates by end-to-end mission completion instead of CPU time alone.

The acceptance scenario intentionally selects `compute:SAT003` over faster `compute:SAT001` because SAT003 has better relay access and finishes the full input-compute-result chain sooner.

Run:

```bash
printf 'load constellation compute configs/compute-ai.yaml
load constellation comm configs/relay-public.yaml
connect constellations compute-ai relay-public
profile on --mode full --run-id joint-dev
submit job workloads/inference.yaml
run 2h
show transfers
profile network
profile bottleneck joint
profile timeline JOB001
profile off
' | python3 -m oslurm.cli
```

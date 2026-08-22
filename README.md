# O-SLURM

The workload manager for computers that don't stay put.

Topology changes.
Sunlight disappears.
Links vanish.
Nodes overheat.
Satellites die.

Your jobs still need to finish.

```bash
make demo
```

Current local result depends on installed backends. This workspace currently has no usable GMAT executable/API and no local Slurm controller/daemon, so the demo exercises the control loop with explicitly labelled mock backends and exits non-zero with `CLOSED LOOP: FAIL`.

```text
GMAT ephemeris/events
        |
        v
O-SLURM prediction: topology + power + thermal + reliability
        |
        v
PredictedResourceWindow
        |
        v
O-SLURM scheduler
        |
        v
Slurm queue/lifecycle/node execution
        |
        v
checkpoint + requeue/migration feedback
```

GMAT: orbital dynamics / ephemeris.

O-SLURM: prediction / constraints / scheduling.

Slurm: queue / workload lifecycle / node execution.

## Commands

```bash
make test
make demo
python3 providers/gmat/adapter.py --scenario providers/gmat/scenarios/leo_demo.yaml --output /tmp/gmat-events.json
```

The GMAT command requires `--allow-mock` for the deterministic fallback. Without that flag, it fails if real GMAT is unavailable.


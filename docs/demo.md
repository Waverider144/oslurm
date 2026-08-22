# Demo

Run:

```bash
make demo
```

The deterministic scenario:

1. Generates four LEO-like satellites.
2. Produces an eclipse entry for `sat002`.
3. Creates event-driven resource windows.
4. Submits a checkpointable workload through the Slurm bridge.
5. Detects the `sat002` SOC violation after eclipse.
6. Restores the workload on `sat004`.

The current local run is expected to end with `CLOSED LOOP: FAIL` because real GMAT and real Slurm are not available.


# O-SLURM Adapter

GMAT-Compute does not depend on O-SLURM. A downstream adapter may map:

```text
ComputeNodeState.node_id          -> OrbitalNodeState.node_id
ComputeNodeState.power_cap_w      -> available_power_w
ComputeNodeState.temperature_c    -> thermal state
ComputeForecast.intervals         -> resource windows
```

O-SLURM remains responsible for placement decisions. GMAT-Compute only exposes
physical and compute-payload state.

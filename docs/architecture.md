# Architecture

O-SLURM keeps four concepts separate:

- `OrbitalNodeState`: observed present state.
- `PredictedResourceWindow`: event-driven prediction over future intervals.
- `OrbitalJobSpec`: workload constraints.
- `PlacementCandidate`: scheduler decision.

The MVP bridge chooses a node externally and passes it to Slurm as a nodelist. Future work should replace that bridge with Slurm `topology/orbital` and `select/orbital` plugins after the closed loop proves the required semantics.


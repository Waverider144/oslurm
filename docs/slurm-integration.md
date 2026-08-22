# Slurm Integration

The current machine exposes Slurm client commands (`sinfo`, `sbatch`, `squeue`, `sacct`) but no `slurmctld` or `slurmd` binaries in `PATH`. `sinfo` cannot connect to a controller.

The MVP therefore implements an external bridge:

```text
O-SLURM candidate node -> sbatch --nodelist=<node>
```

When a real controller is unavailable the bridge is explicitly labelled `MOCK`, and `make demo` exits with `CLOSED LOOP: FAIL`.

The next Slurm step is a local containerized or native Slurm cluster with nodes `sat001` through `sat004`, followed by a small `job_submit/orbital` plugin that only validates metadata.


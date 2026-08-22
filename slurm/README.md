# Slurm

This directory is reserved for native Slurm integration.

MVP status:

- External bridge implemented in `oslurm/slurm_bridge.py`.
- `osbatch` stores O-SLURM metadata in SQLite and submits through the bridge.
- `job_submit/orbital` is documented but not compiled because the local machine does not have Slurm development headers or a working local controller.


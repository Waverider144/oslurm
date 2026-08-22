# job_submit/orbital

Planned first plugin responsibility:

- Validate that submitted Slurm jobs have matching O-SLURM metadata.
- Reject structurally impossible metadata.
- Avoid GMAT propagation or expensive prediction inside `job_submit`.


# GMAT Plugin Boundary

The current implementation deliberately does not guess the GMAT R2026a C++ plugin ABI.

Implemented now:

- `adapters/gmat/gmat_comm_ephemeris.py` reads real GMAT/O-SLURM ECI JSON event output.
- It computes pairwise range and Earth line-of-sight checks.
- It writes contact windows that GMAT-Comm and O-SLURM can consume.

Future GMAT plugin:

- Wrap GMAT spacecraft state access.
- Export the same contact-window JSON or protobuf shape.
- Keep `core/` free of GMAT includes so C++ unit tests remain scheduler and simulator neutral.

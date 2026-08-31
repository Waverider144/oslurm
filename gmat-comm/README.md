# GMAT-Comm

GMAT-Comm is a scheduler-neutral communication payload and network planning layer for flight-compute experiments. It is designed to sit beside GMAT-Compute: GMAT supplies orbital geometry, GMAT-Comm turns geometry plus terminal profiles into contact windows and transfer envelopes, and O-SLURM consumes those windows when it co-schedules compute placement and data movement.

The core C++ library intentionally has no GMAT headers. GMAT coupling is kept in adapters and a future plugin boundary so the communication model can be tested without a GMAT build tree.

## What Is Implemented

- C++20 core communication payload API with terminals, buffers, transfer intents, contact windows, reservations, and deterministic route planning.
- Analytic envelope provider for early studies.
- Measured file envelope provider backed by CSV curves and manifest provenance.
- Python provider API with analytic and measured implementations.
- GMAT ECI JSON geometry adapter that reads O-SLURM/GMAT event output and emits line-of-sight contact windows.
- Continuous direct routing and two-hop temporal store-carry-forward routing.
- Unit tests and a relay demo.

## Build And Test

```bash
cmake -S gmat-comm -B gmat-comm/build
cmake --build gmat-comm/build
ctest --test-dir gmat-comm/build --output-on-failure
python3 -m unittest discover -s gmat-comm/tests -p 'test_*.py'
```

Or:

```bash
make -C gmat-comm test
make -C gmat-comm demo
```

## Interface Boundary

GMAT-Comm accepts geometry, not scheduler decisions:

- Input: ECI positions, velocities, simulation time, range, relative velocity, line-of-sight state, terminal profile ids, and transfer demand.
- Output: contact windows, conservative bandwidth, latency, loss, acquisition time, confidence, route candidates, and reservation state.
- Ownership: GMAT owns orbital truth, GMAT-Comm owns communication envelope computation, O-SLURM owns task placement and reservation policy.

## Repository Layout

- `core/`: GMAT-free C++ API and implementation.
- `adapters/gmat/`: JSON adapter for GMAT/O-SLURM ECI event output.
- `providers/python/`: Python provider interface for measured or analytic envelopes.
- `measured/`: example CSV envelope data and schema notes.
- `profiles/`: reusable communication terminal profiles.
- `api/proto/`: stable protobuf surface for future service boundaries.
- `plugin/gmat/`: placeholder for a real GMAT plugin build once GMAT ABI details are pinned.
- `docs/`: architecture and integration notes.

## Known Limits

- The GMAT plugin itself is not compiled here; the adapter consumes GMAT-derived JSON and avoids guessing the GMAT R2026a plugin ABI.
- Current routing is deterministic and conservative: direct contacts plus two-hop store-carry-forward.
- Measured envelope files are example data, not operator-validated terminal performance.

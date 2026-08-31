# Visibility Gap Analysis

Baseline commands were run from `/home/ngphpc/Desktop/OSLURM`.

Current findings:

- Compute topology DTOs live in `core/src/predictor/topology.rs`; before this change there was no shared visibility DTO or guard.
- Python multi-constellation contact creation lived in `oslurm/network/runtime.py` and created `ContactWindow` instances from scenario constants.
- GMAT-Comm adapter had its own line-of-sight helper and did not share a visibility provider with O-SLURM.
- No current code exposes GMAT `Spacecraft` attitude, `Sensor`, `FieldOfView`, `ContactLocator`, or `EventLocator` through a compiled plugin ABI.
- GMAT-Compute uses a real `GmatConsole` adapter for ECI samples, but its core correctly remains scheduler-neutral and GMAT-header-free.
- Browser visualization consumes static GMAT ECI JSON and is not a source of truth for scheduler visibility.

Previous visibility assumptions:

- Range and hand-authored contact windows could imply a communication path.
- FOV was not GMAT-native.
- Unknown attitude was not explicitly represented.

Correction made in this pass:

- `oslurm.visibility` is now the shared canonical Python visibility layer.
- `gmat-comm/adapters/gmat/gmat_comm_ephemeris.py` now reuses that visibility layer.
- O-SLURM network contact creation fails closed and `NetworkPlanningService.add_contacts` rejects invisible contacts.
- A GMAT plugin visibility submodule exists under `plugin/gmat/visibility/` with scheduler-neutral C++ DTOs.

Remaining gap:

- Real GMAT-native attitude/FOV integration is still blocked by the unpinned local GMAT plugin ABI. The module therefore exposes the boundary and fails closed when attitude transforms are unavailable.

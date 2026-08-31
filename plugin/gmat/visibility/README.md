# GMAT Visibility Module

This is the GMAT-native boundary for visibility and terminal field-of-view work.

The module is deliberately separate from GMAT-Compute, GMAT-Comm, and O-SLURM scheduling code. Its public API uses scheduler-neutral DTOs: `VisibilityQuery`, `VisibilityResult`, and `VisibilityWindow`.

Current status:

- Earth occultation API supports WGS84 ellipsoid parameters plus the older spherical compatibility helper.
- Cone FOV API is present.
- GMAT spacecraft attitude access is not implemented because the local GMAT plugin ABI has not been pinned.
- Unknown or unavailable pointing state fails closed.

Future implementation should fill `GmatGeometryAdapter` from GMAT `Spacecraft` state and attitude transforms, then use `GmatFieldOfViewProvider` to evaluate terminal boresight against the target LOS vector.

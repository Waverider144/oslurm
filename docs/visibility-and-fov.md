# Visibility And FOV

Visibility is split into three different layers.

1. Body occultation decides whether a line segment between endpoints intersects an occulting body.
2. Field of view decides whether source and destination terminal geometry can point at that line of sight.
3. Terminal capability decides whether a geometrically valid link can carry traffic with enough bandwidth, latency, loss, confidence, power, and acquisition margin.

The pipeline is:

```text
Orbit
↓
LOS / occultation
↓
FOV
↓
pointing
↓
terminal capability
↓
link
```

O-SLURM core must not calculate spacecraft-native FOV from guessed attitude. The intended production path is:

```text
GMAT orbit + attitude truth
↓
GMAT Visibility Plugin
↓
VisibilityResult
↓
GMAT-Compute / GMAT-Comm / O-SLURM
```

Current fidelity:

- Earth occultation: WGS84 Earth ellipsoid with configurable safety clearance.
- Horizon prefilter: conservative ellipsoid-safe horizon prefilter using the smallest body axis, followed by exact testing.
- Exact test: finite line-segment intersection against the effective Earth ellipsoid.
- Ground links: local horizon check using the ellipsoid surface normal for surface endpoints.
- FOV: cone field-of-regard when a body-to-inertial transform is supplied.
- Unknown attitude/FOV state: conservative fail closed.
- Pointing rate: not yet implemented.
- Sun exclusion: schema/API placeholder, validation fails if requested.
- Earth-limb exclusion: schema/API placeholder, validation fails if requested.
- Moon exclusion: schema/API placeholder, validation fails if requested.

Contact windows are the intersection of geometric visibility and terminal/FOV validity. The implementation slices windows over deterministic propagation samples and keeps transition tolerance configurable. `AnalyticSphereVisibilityProvider` remains available only as a unit-test and cross-validation baseline.

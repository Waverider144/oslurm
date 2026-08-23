# GMAT Plugin

Current status:

```text
GMAT Plugin: PARTIAL
GMAT Runtime Integration: REAL
```

The working implementation is `adapters/gmat/gmat_ephemeris.py`. It generates a
GMAT script, runs `GmatConsole`, parses a report file, and emits scheduler-neutral
ECI samples.

The future plugin should stay thin:

```text
GMAT Spacecraft state
        ↓
OrbitalEnvironmentState
        ↓
ComputePayload core
```

GMAT-specific headers and ABI code must remain inside `plugin/gmat/` and
`adapters/gmat/`. The core must never include GMAT headers.

# O-SLURM Mission Control Visualization

This folder contains the static GitHub-ready visualization for O-SLURM.

## Files

- `index.html`: page markup and styles.
- `app.js`: object-oriented browser application entrypoint. `MissionControlApp` owns the canvas view, event panel, command console, ephemeris loader, satellite inspector, and replay loop.
- `comm-overlay.js`: independent object-oriented communication overlay. It listens to `oslurm:ephemeris-loaded` and `oslurm:orbit-render`, then draws GMAT-Comm transfer paths and the co-scheduler panel.
- `comm-trace.json`: static communication/co-scheduling trace for GitHub Pages visualization.
- `gmat-events.json`: scheduler-neutral GMAT ECI export consumed by the browser.
- `earth-blue-marble.jpg`: local Earth texture used by the canvas renderer.

## GMAT Boundary

The browser does not talk to GMAT directly.

GMAT is run offline by the repository adapter:

```bash
python3 providers/gmat/adapter.py \
  --scenario providers/gmat/scenarios/leo_demo.yaml \
  --output docs/visualization/gmat-events.json
```

That adapter calls the local GMAT console when available, parses the generated orbit report, derives event-driven orbital events such as eclipse entry/exit, and writes scheduler-neutral JSON:

```json
{
  "samples": [
    {
      "node_id": "sat001",
      "timestamp_ms": 1787356800000,
      "position_eci_m": [ ... ],
      "velocity_eci_mps": [ ... ],
      "in_sunlight": true
    }
  ],
  "events": [
    {
      "type": "ECLIPSE_ENTRY",
      "node_id": "sat001",
      "timestamp_ms": 1787357040000
    }
  ]
}
```

`MissionControlApp` loads this file with:

```js
fetch("gmat-events.json", { cache: "no-store" })
```

The visualization then computes display-only orbital elements and renders the Earth, ECI paths, sunlight/night side, event markers, and satellite parameter panel in the browser.

The display Earth model now uses WGS84 ellipsoid constants:

```text
equatorial radius = 6378.137 km
polar radius      = 6356.752314245 km
```

Altitude values in the satellite parameter panel are measured against the local ellipsoid surface radius rather than a fixed mean-radius sphere. The latitude/longitude grid is generated from the ellipsoid axes, and the HUD labels the active visibility model as `ellipsoid:wgs84`.

The raster Earth texture is still sampled as a longitude/latitude image for display. Scheduler visibility truth remains outside the browser in `oslurm.visibility` and GMAT-Comm.

## GMAT-Comm Boundary

The browser communication overlay does not run GMAT-Comm. It consumes a static scheduler-neutral trace:

```js
fetch("comm-trace.json", { cache: "no-store" })
```

`comm-overlay.js` is mounted separately from `app.js`. The main orbital app emits render context events; the communication module listens, projects relay/ground/compute endpoints, and draws transfer paths. This keeps communication visualization replaceable when live `profiles/<run-id>/events.jsonl` export is added later.

## Slurm Boundary

The browser does not submit jobs to Slurm directly.

The command console renders a Slurm-compatible batch template so the UI mirrors the operational shape of an O-SLURM uplink:

```bash
#SBATCH --nodelist=sat[001-004]
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=...
#SBATCH --mem=...
export OSLURM_TARGETS=sat001,sat002,sat003,sat004
export OSLURM_ECI_M=...
```

When the user presses send, `MissionControlApp` parses the `#SBATCH` directives and `OSLURM_*` environment variables locally, then drives an animated execution replay through the same conceptual stages used by the real O-SLURM path:

1. command accepted
2. Slurm allocation shape parsed
3. satellite leases accepted
4. matrix-solve progress evolves
5. orbital/power degradation triggers scheduler rebalance
6. checkpoint/migration/complete events update the panel

For real execution, the repository-side bridge is responsible for talking to Slurm:

```bash
make demo
make satellite-demo
```

Those commands use the Python O-SLURM modules, GMAT adapter output, and the local Slurm bridge under `oslurm/slurm_bridge.py`. This static visualization intentionally remains scheduler-neutral and browser-only so it can be hosted on GitHub Pages without a backend service.

## Updating The Visualization Data

Regenerate the GMAT input JSON, then start the static server:

```bash
python3 providers/gmat/adapter.py \
  --scenario providers/gmat/scenarios/leo_demo.yaml \
  --output docs/visualization/gmat-events.json

make visualize
```

Open:

```text
http://localhost:8081
```

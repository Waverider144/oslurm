# O-SLURM Mission Control Visualization

This folder contains the static GitHub-ready visualization for O-SLURM.

## Files

- `index.html`: page markup and styles.
- `app.js`: object-oriented browser application entrypoint. `MissionControlApp` owns the canvas view, event panel, command console, ephemeris loader, satellite inspector, and replay loop.
- `execution-replay.js`: `ExecutionTraceReplay` loads a single recorded experiment and maps its simulation clock to actual GMAT sample epochs.
- `ground-track.js`: independent `GroundTrackView`; UTC/GMST ECI-to-ECEF conversion, WGS84 subpoints, flat Earth map, past/predicted tracks, pan/zoom and selection.
- `execution-trace.json`: self-contained real Ax=b experiment, including full-orbit ephemeris, Flight Recorder events, verified result and run ID.
- `comm-overlay.js`: independent object-oriented communication overlay. It listens to `oslurm:ephemeris-loaded` and `oslurm:orbit-render`, then draws GMAT-Comm transfer paths and the co-scheduler panel.
- `comm-trace.json`: static communication/co-scheduling trace for GitHub Pages visualization.
- `gmat-events.json`: scheduler-neutral GMAT ECI export consumed by the browser.
- `earth-blue-marble.jpg`: local Earth texture used by the canvas renderer.

## GMAT Boundary

The browser does not talk to GMAT directly. When `execution-trace.json` exists,
the view uses the ephemeris embedded in that experiment so orbit and execution
cannot silently come from different runs. `gmat-events.json` remains a fallback
for orbit inspection without execution replay.

GMAT is run offline by the repository adapter:

```bash
python3 providers/gmat/adapter.py \
  --scenario providers/gmat/scenarios/leo_demo.yaml \
  --horizon-s 5760 --step-s 60 \
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

Altitude values in the satellite parameter panel are measured against the local ellipsoid surface radius rather than a fixed mean-radius sphere. The latitude/longitude grid is generated from the ellipsoid axes.

The raster Earth texture is still sampled as a longitude/latitude image for display. Scheduler visibility truth remains outside the browser in `oslurm.visibility` and GMAT-Comm.

## GMAT-Comm Boundary

The browser communication overlay does not run GMAT-Comm. It consumes a static scheduler-neutral trace:

```js
fetch("comm-trace.json", { cache: "no-store" })
```

`comm-overlay.js` is mounted separately from `app.js`. The main orbital app emits
render context events; the communication module listens and draws endpoint markers
and relay trails. Communication connection lines are disabled. This keeps the
communication visualization replaceable when live transfer export is added later.

When a recorded Ax=b run is loaded, this legacy communication trace is suppressed.
The independent communication module consumes `execution-trace.json.communication`:
real GMAT relay samples, GMAT-Comm contact windows, checkpoint plans and reservation
states. The Co-Scheduler advances queued/waiting/transferring/delivered states on
the main simulation clock. Relay positions are not synthesized for these runs.
The explicit `shared` baseline has no radio reservations and remains idle.

## Node Telemetry And Ground Track

The MAP view uses the existing Earth image and the same run's satellite/relay
samples. It renders a longitude/latitude flight-control display with solid past
and dashed future tracks. Longitude uses GMST at the actual sample UTC; latitude
uses WGS84 geodetic coordinates. The 3D grid/texture use the same Earth orientation.

SoC/Thermal cards now consume `NODE_OPERATING_SNAPSHOT` events through
`ExecutionTraceReplay.telemetryAt(node, simulationTimeS)`. They select the latest
snapshot at or before the replay clock, never a future value. Missing node data
remains `--`; model-generated battery/thermal values include provenance in their
tooltips. These are analytic digital-twin outputs, not measured flight telemetry.
The orbital parameter inspector remains fixed to the manually selected sample.

The Scheduler shows the policy, destination, authority lease and modeled ground
connectivity. The `autonomous` policy runs the existing satellite-local core with
resource forecasts and explicit routed peer advertisements. See
[the experiment](../orbit-axb.md) for the control-message simulation boundary.

Optional browser regression (Chrome installed locally, server already running):

```bash
python3 -m pip install -r requirements-dev.txt
python3 tests/browser/mission_control.py --url http://localhost:8081/
```

## Slurm Boundary

The browser does not submit jobs to Slurm directly.

The execution console displays the recorded experiment's reproducible command:

```bash
python3 -m oslurm.orbit_benchmark --backend slurm --publish
```

The replay icon plays the actual recorded residuals, node placements,
checkpoint restores, eclipse events, and completion/failure state. The displayed
command is read-only; the browser never executes shell input. `ExecutionTraceReplay`
uses event simulation timestamps for both orbital position and the UTC clock.
Only actual O-SLURM scheduler decisions enter the blue Change filter.

For real execution, the repository-side bridge is responsible for talking to Slurm:

```bash
make demo
make satellite-demo
python3 -m oslurm.orbit_benchmark --backend slurm --publish
```

The Ax=b command submits real batch jobs and validates their exit status and
worker identity. Its default local backend also performs real calculations but
does not use Slurm. See [experiment details](../orbit-axb.md) for the simulation
throughput model and checkpoint transport limitations. This visualization stays
static and can be hosted on GitHub Pages without a backend service.

## Updating The Visualization Data

Regenerate the complete experiment bundle, then start the static server:

```bash
python3 -m oslurm.orbit_benchmark --backend local --publish

make visualize
```

Open:

```text
http://localhost:8081
```

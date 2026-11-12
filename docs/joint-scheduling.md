# Joint Compute and Communication Scheduling

## Modeled Multi-Job Run

From the repository root:

```bash
make joint-demo
```

This executes `benchmarks/joint-lifecycle.cli`: two mission jobs compete for
compute slots, relay buffers, contact byte budgets, and half-duplex radios. It
advances the simulation in steps and writes a unified profile to
`profiles/joint-lifecycle/`. Repeating the command replaces that named profile;
change `--run-id` in a copied CLI script to retain independent experiments.

Expected modeled delivery times with the supplied configuration:

| Job | Compute Node | Relay | Compute Interval | Ground Delivery |
| --- | --- | --- | --- | --- |
| JOB001 | SAT003 | RELAY-A | 47.740-267.740 s | 277.213 s |
| JOB002 | SAT002 | RELAY-B | 63.062-323.062 s | 328.158 s |

At T+1 s neither job has started computing. At T+270 s JOB001 is waiting
for result delivery while JOB002 is computing. A mission is complete only when
its result transfer reaches the configured destination, not when compute ends.

## Real Ax=b Run

```bash
make joint-axb
# Or execute on the actual Slurm node selected by the joint decision:
./scripts/start-local-slurm.sh
python3 -m oslurm.joint_execution --backend slurm --dimension 65536
# Real worker + profile inspection in one CLI session:
python3 -m oslurm.cli < benchmarks/joint-real-axb.cli
```

`run joint-axb` is a separate, self-recording single-mission execution path.
It uses the same joint planner, contact/radio/buffer reservations and configured
resource admission as `submit job`, but replaces the modeled compute interval
with a real conjugate-gradient solve. Existing `submit job` / `run 1h` behavior
remains modeled. Use `profile off` before `run joint-axb`.

Real missions default to `--contact-mode gmat`: real GMAT propagates all four
compute nodes and Relay-A/B through the mission deadline. No GMAT availability
means a failed mission, not a silent mock or fixture fallback. Use the explicit
`--contact-mode fixtures` only to reproduce the original static scenario.

1. Generate a full CG input checkpoint for the deterministic SPD system
   `tridiag(-1, 2.0001, -1)`. Reserve the actual NPZ byte count, not a dummy payload.
2. Select a compute node and atomically reserve upload and predicted downlink.
3. Wait on the simulation clock for upload delivery; only then copy and SHA256
   verify the input in that node's staging directory and launch the worker.
4. Measure launch-to-worker-return elapsed time. Actual completion is compute
   start plus that duration, at **1 host second = 1 simulation second**. Slurm
   queue, launch and wait overhead count; numerical kernel time is reported
   separately. No artificial sleep stretches the solve to the prediction.
5. Validate the solved checkpoint's job identity and true Ax=b residual. In an
   isolated transaction, remove the unused predicted downlink and reserve the
   earliest feasible route after actual completion for the actual result size.
   An early finish may advance delivery if a contact is open; a late finish can
   move to a subsequent contact. Existing competing reservations remain binding.
6. At modeled radio arrival, stage the solved NPZ back to the ground, verify its
   SHA256, reconstruct the same system and check the true residual again. Only
   then emit `MISSION_JOB_COMPLETED` and `JOB_COMPLETED`.

`configs/compute-profiles.json` explicitly maps logical nodes to `slurm_node`,
for example `compute:SAT003` to `sat003`. The Slurm backend checks both node
availability and worker-reported node/job identity; it never falls back to mock
execution. Local mode runs the real solver on the host with logical satellite
placement only. The local Slurm nodes also share one physical host.

Options include `--dimension`, `--tolerance`, `--max-iterations`, `--seed`,
`--deadline-s` and `--run-id`. Insufficient iterations, worker failure, corrupt
input/result or no downlink before the deadline produce `status: failed`, a
`JOB_FAILED` event and reservation cleanup, without false mission completion.
The standalone module exits nonzero on a failed mission; the interactive CLI
returns the structured result with its status. A failed replan does not mutate
the old plan until explicit failure cleanup releases it.

Each run writes `profiles/joint-axb-<id>/` (or the explicit run ID), including:

- `result.json`: prediction versus actual completion, numerical residual,
  kernel/worker elapsed time, revised delivery, wait time, hashes and reservations.
- `ground/input.npz` and `ground/result.npz`: submitted state and verified result.
  The result is a portable solved checkpoint containing x and full restart state,
  not a dense copy of A. A failed mission may have no ground result.
- `nodes/<logical-node>/checkpoint.npz`: worker-local solution/staging file.
- `segment-000.json`: worker wall timestamps, iterations, residual and Slurm
  identity. Its `sim_s` is null: completion is measured by the coordinator,
  rather than guessed in advance by the worker.
- `events.jsonl`, `manifest.json`, `metrics.json`, `perfetto.json`: unified
  profile, including `NETWORK_REPLAN` with predicted/actual completion and
  updated delivery time (or an infeasible outcome).

The real mission runner is deliberately isolated to one job per invocation.
It does not yet execute several measured workers concurrently or feed measured
durations back into future compute profiles.

## Dynamic Windows

`configs/ground-stations.json` defines WGS84 latitude, longitude, altitude and
minimum elevation (degrees). The supplied station is a demo equatorial site at
0 latitude / 0 longitude, 100 m altitude and a 10-degree elevation mask; it is
not an asserted real flight-control location. Override with `--ground-stations`.

Ground sites rotate using approximate GMST. Spacecraft use GMAT's propagated
EarthMJ2000Eq Cartesian states. This is **not** a full IAU/ITRF-to-MJ2000 frame
transformation: precession/nutation, polar motion and UT1 corrections are not
implemented. The approximation and source are preserved in run metadata.

The default `--contact-step-s 30` evaluates endpoints and three interior samples
per interval. Ground positions are evaluated on the rotating ellipsoid at each
interior sample, not linearly interpolated through the Earth. Spacecraft use
piecewise-linear interpolation. WGS84 occultation, station elevation and maximum
range must pass all five tests before accepting an interval; consecutive
accepted intervals merge into windows. Boundaries are quantized to the input
step, not precision root-finding, and finite sampling is not a mathematical
guarantee of visibility between every test point. Decrease the step for finer
screening. Windows never extend beyond supplied ephemeris coverage.

Each window's worst sampled range feeds the existing GMAT-Comm analytic
envelope provider. Conservative goodput, acquisition time and propagation
latency drive half-duplex reservations and byte capacity. `--bandwidth-mbps`
caps the modeled rate (default 8 Mbps); it is not measured RF throughput.

`gmat-events.json` records propagated states and ground-site definitions;
`contacts.json` records the generated contact plan, link roles and limits.
The manifest hashes both artifacts. Prepared contacts reflect predicted motion;
they are not updated from live telemetry during this single-job run.

## Mission Profiling

```text
run joint-axb --backend local --deadline-s 1800 --contact-step-s 30
profile mission
profile mission JOINT-AXB001
profile network
profile timeline JOINT-AXB001
```

Every real mission also writes `mission-profile.json`. For completed missions,
the non-overlapping simulation-time accounting is:

```text
mission latency = input elapsed + compute queue + measured worker + result elapsed
transfer elapsed = window waiting + link occupancy
link occupancy = acquisition + serialization + propagation
```

Waiting includes both initial contact wait and store-and-forward gaps between
hops. Numerical kernel time and worker overhead partition the measured worker
duration; overhead includes startup, Slurm queue/wait and checkpoint I/O, and is
not added again. Host-only GMAT propagation, contact construction, initial
planning and replanning times are reported separately, not charged twice to the
simulation clock. Coordinator validation/staging wall costs are not separate
simulation stages. Missing completion leaves latency/accounting null rather
than falsely reporting a successful zero-duration mission.

`unattributed_s` is a check on the sum (approximately zero apart from timestamp
rounding). Perfetto exports input, actual compute and result spans anchored at
their start times, rather than drawing completion-duration spans into the
future. `NETWORK_REPLAN` records feasibility and measured host planning cost.

## CLI Inspection

Within a CLI session, after loading/connecting constellations and submitting:

```text
show jobs
scheduler explain job JOB001
show reservations
run 1s
show jobs
run 269s
show jobs
run 1h
profile network
profile timeline JOB001
profile off
```

`scheduler explain job` exposes all candidate outcomes, compute-only baseline,
selected placement, upload path, compute times, downlink path, and delivery time.
Trace decision cost is measured host wall time, not a fabricated constant.
`network_changed_compute_placement` compares against the resource-eligible,
queue-aware compute-only baseline, and can be false.

`deadline` in a job YAML is relative to submission, while profile
`available_at_s` is an absolute simulation timestamp. Job IDs must be unique in
a runtime session; duplicate submissions fail without modifying reservations.

## Admission and Planning

`configs/compute-ai.yaml` references `compute-profiles.json`, resolved relative
to the constellation file. Each listed compute node requires a JSON profile:

```json
{
  "compute:SAT003": {
    "compute_time_s": 220,
    "available_at_s": 0,
    "soc": 0.70,
    "predicted_min_soc": 0.55,
    "reserve_soc": 0.30,
    "temperature_c": 42,
    "predicted_max_temperature_c": 60,
    "thermal_limit_c": 70
  }
}
```

These are configured estimates, not live telemetry or measured worker speed.
If a predicted bound is absent, admission uses its current snapshot; if a
snapshot is also absent, defaults are SoC 1.0 and temperature 20 C. Limits
default to 0.30 and 70 C. The current snapshot must also be safe; a more
optimistic predicted bound cannot override an unsafe current state.
Unsafe candidates report `POWER_RESERVE` or
`THERMAL_LIMIT`; invalid/non-finite numeric inputs fail closed.

For each eligible node the planner evaluates available direct and one-relay
input routes. In an isolated network snapshot it reserves each input route,
waits for both input arrival and compute availability, and searches for a
deliverable result route. It selects the earliest feasible end-to-end finish.
Missing paths report `NETWORK_INPUT` or `NETWORK_RESULT`, including reservation
conflicts or insufficient buffer capacity encountered during planning.

Both selected transfers are reserved and committed atomically. A failure in
either leaves live byte budgets, reservations, buffers, and ID counters
unchanged. Compute availability advances to the scheduled compute finish.
Standalone `transfer submit` also reserves real simulated network capacity,
so background traffic can affect later placement.

`run` processes only events up to the requested time, including when profiling
is disabled. Completed transfers release buffer reservations and retain past
radio occupancy and consumed contact bytes. Repeated runs do not duplicate
completion events. Profiles record accepted/committed/completed reservation
transitions and separate compute completion from ground delivery.

## Boundaries

- The modeled multi-job CLI scenario uses configured compute durations and static, analytic
  WGS84-visibility-gated contact fixtures. It does not launch Slurm jobs,
  propagate GMAT or send files over physical radios.
- The separate `run orbit-axb` experiment executes real Ax=b segments on local
  workers or Slurm, uses GMAT propagation and modeled GMAT-Comm checkpoint
  transfers. It is not yet driven by this mission input/result planner.
- Routing supports direct delivery or one intermediate buffered node, not an
  arbitrary multi-relay graph. Plans are feasible candidates, not a proof of a
  global optimum over arbitrary start times and job reorderings.
- Relay buffers are conservatively held per transfer from commitment through
  delivery, including future result transfers. Time-indexed buffer reuse and
  preemption are not implemented. Completed radio occupancy remains in history.
- Resource snapshots are not automatically evolved by this scenario. The
  full-orbit experiment has its own analytic power/thermal integration.
- Atomicity assumes the existing single-threaded simulator. A concurrent server
  needs serialization around planning, reservation and contact updates.
- The real joint runner uses dynamic windows by default; explicit fixture mode
  is retained for regression tests. Radio delays are modeled; actual payload
  movement is local verified staging, not physical RF transmission.
- The browser's published full-orbit trace is unchanged by either joint runner.

The next integration boundary is handling several measured workers concurrently
with compute-slot overruns and replanning, then improving frame transformations
and contact-boundary refinement for higher-precision mission analysis.

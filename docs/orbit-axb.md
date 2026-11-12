# Full-Orbit Ax=b Experiment

This experiment runs a real matrix-free conjugate-gradient solve against GMAT
orbital samples, preserves the full Krylov state across execution segments, and
exports one self-contained execution trace for the mission-control view.

Checkpoint migration defaults to `--checkpoint-transport gmat-comm`. The
benchmark propagates RELAY-A/B with GMAT and reserves direct or two-hop
store-carry-forward delivery before restoration on another compute node.

## Run

Install the Python numerical dependency once:

```bash
python3 -m pip install -r requirements.txt
```

Real GMAT is required. There is no automatic mock fallback in this benchmark.
The default local backend executes real numerical calculations on this computer:

```bash
make orbit-axb
```

For real Slurm node execution:

```bash
./scripts/start-local-slurm.sh
python3 -m oslurm.orbit_benchmark --backend slurm --publish
```

Each segment is a real `sbatch --wait` job. A nonzero exit, unavailable controller,
unavailable node, or mismatched worker node causes an error. No simulated Slurm
success is substituted. Jobs are sequential segments of one solve, not four-way
MPI matrix partitioning. All four local Slurm nodes share the same physical host.

Use the existing Profile CLI in a single session:

```bash
python3 -m oslurm.cli < benchmarks/orbit-profile-axb.cli
```

Or enter `run orbit-axb --backend slurm --publish`, then `profile summary`,
`profile scheduler`, and `profile timeline AXB001`. This command owns its recorder;
close an existing `profile on` session first. Every invocation uses a new run ID.
An explicitly reused run ID is rejected instead of overwriting reports.

## Numerical Problem And Clock

- `A = tridiag(-1, 2.0001, -1)`, symmetric positive definite, float64.
- Default dimension: 65,536; seed: 42.
- The known reference solution is seeded random data; `b = A x_reference`.
- Storage and matrix-vector products are O(n); no dense 65,536-square matrix.
- Success requires independently recomputed `||b-Ax|| / ||b|| <= 1e-8` from the
  persisted checkpoint. The solution error is reported separately.
- Checkpoints contain x, r, p, squared residual, iteration, seed, dimension,
  tolerance, and schema version. They are written atomically.

GMAT propagates four compute spacecraft and RELAY-A/B for 5,760 seconds at 60-second
sampling, exceeding the roughly 5,730-second orbital period. Timestamps are
derived from the GMAT report epochs. Eclipse flags retain the adapter's cylindrical
shadow approximation with a fixed +X Sun and spherical Earth; they are not native
GMAT shadow-model outputs. Reported revolution counts are calculated
from the propagated positions, not the animation duration.

RELAY-A/B have a 42,164 km geocentric circular radius, initial phases 0 and 120
degrees, and inclination 2 degrees. Their GMAT samples are separate from the
four compute nodes in the replay bundle; display offsets are not used.

Simulation time and wall time are separate. The declared model allows 0.18 CG
iterations per simulation second in sunlight, multiplied by 0.35 in eclipse.
The `eclipse` policy moves the checkpoint to a sunlit node at sample boundaries;
the `fixed` baseline stays on sat001. The default rate is chosen to span roughly
one orbit. It is not a measured spacecraft throughput or a calibrated power model.
The local solve takes much less wall time than its modeled simulation duration.

Useful options: `--dimension`, `--seed`, `--tolerance`, `--iteration-rate`,
`--eclipse-factor`, `--policy autonomous|fixed|eclipse`, `--backend local|slurm`, `--run-id`,
and `--publish`. Insufficient iteration budget produces `JOB_FAILED` and a nonzero
exit from `python3 -m oslurm.orbit_benchmark`.

## Checkpoint Network

`oslurm.network.checkpoint.CheckpointNetwork` calls the Python APIs in
`gmat-comm/adapters/gmat/gmat_comm_ephemeris.py` and
`gmat-comm/providers/python/gmat_comm_provider.py`. Contact construction checks
both endpoints and three interior points of each piecewise-linear ECI interval
against WGS84. Contacts never extend past the final ephemeris epoch.

Goodput uses the analytic bandwidth lower bound, capped by
`--comm-bandwidth-mbps` (default 8 Mbps), reduced by upper-bound packet loss.
Each hop includes upper-bound acquisition time and propagation latency.
`--comm-max-range-m` defaults to 80,000,000; `--relay-buffer-mb` defaults to 64
decimal MB. Each spacecraft has one modeled half-duplex `radio0` terminal.

For the `eclipse` baseline, the scheduler ranks deliverable sunlit targets by earliest
arrival. A missing route or insufficient buffer defers migration: the source
continues at its sunlight/eclipse compute rate. Targets already in eclipse at
arrival and deliveries beyond the next computation window are rejected.

Reservation acceptance atomically validates contact capacity, terminal occupancy
and intermediate relay buffers. Committed transfers block overlapping terminal
intervals. Expiry, abort and completion release reserved relay storage.

The real checkpoint file size determines transferred bytes. Waiting, acquisition,
serialization and propagation consume simulation time with zero job progress.
After arrival, only the remaining fractional compute interval receives an
iteration budget. A per-node copy is staged and SHA-256-verified before restore;
the process does not sleep for modeled radio time.

Compare communication-aware execution with the former zero-radio-cost baseline:

```bash
python3 -m oslurm.orbit_benchmark --checkpoint-transport shared
python3 -m oslurm.orbit_benchmark --checkpoint-transport gmat-comm
```

Reduce `--comm-bandwidth-mbps` or `--relay-buffer-mb` to exercise constrained
or undeliverable checkpoints. An orbit deadline miss remains a failed run;
the code does not fabricate convergence.

## Autonomous Policy And Telemetry

The default policy is now `autonomous`. `OrbitAutonomy` runs an existing
`DeterministicSatelliteScheduler` instance for each compute node. Decisions occur
at five-minute boundaries and sampled eclipse transitions. It retains a safe,
sunlit local placement to avoid churn; on local risk it considers valid peer
advertisements backed by deliverable GMAT-Comm checkpoint routes. The core ranks
feasible candidates by worst normalized safety margin. The next nominal 120
seconds of work is checked against a resource forecast of up to 300 seconds;
execution also has a per-sample power/thermal safety interlock.

`LocalSchedulingContext.peer_delivery_s` is an explicit optional routed-peer
contract. It contains validated delivery durations, not invented physical ISLs.
Omitting it preserves the original direct-neighbor-only policy. The core uses
these durations for migration feasibility and margin calculations instead of the
legacy fixed 27-second estimate. The provider-neutral scheduler imports neither
Slurm nor GMAT-Comm.

Default ground disconnection is T+240 seconds; autonomous authority lasts through
the orbit horizon. `--ground-disconnect-s` and `--authority-until-s` control these
scenario assumptions. Expired authority rejects new decisions and pauses the next
execution interval; a previously authorized interval may finish before the next
reevaluation. Peer handoffs use offer/accept/commit with compute reservations and
idempotent commit handling, followed by the separately reserved checkpoint delivery.
Protocol messages and agents run in-process; this is not an onboard daemon or
measured control-plane radio implementation.

`NodeTelemetry` integrates the existing battery and thermal models for every
compute node on the same simulation clock. Sunlight comes from the GMAT adapter;
actual executed/idle intervals select compute or idle loads. Transfer waiting is
idle time. The nominal communication load is included in the power configuration;
per-radio dynamic power is not yet coupled. Initial values default to SoC 0.42
and temperature 42 C, configurable with `--initial-soc` and
`--initial-temperature-c`. CPU work pauses when its interval forecast would
violate the battery reserve or soft thermal limit.

Snapshots are `NODE_OPERATING_SNAPSHOT` events containing SoC, temperature,
limits, sunlight and CPU state, with `telemetry_source=analytic_power_thermal`.
The bundle includes the model configurations under `telemetry`; these values are
digital-twin telemetry, not hardware sensor measurements. Flight Recorder now
receives modeled node utilization as well as network/compute events.

## Outputs And Baseline

Each run writes `profiles/<run-id>/`:

- `result.json`: verified residual, solution error, iteration count, modeled finish
  time, measured compute/segment/total wall time, migration count and Slurm job IDs.
- `checkpoint.npz`: final solver state, reloadable with `ConjugateGradient.load`.
- `nodes/<node>/checkpoint.npz`: per-node execution/staging files.
- `checkpoint-network.json`: contacts, relay ephemeris, transfer plans,
  reservation states, buffer capacities and checksums.
- `segment-*.json`, `ticks-*.json`, `slurm-*.out`: worker results and execution evidence.
- `gmat-events.json`: full-orbit GMAT output for this run.
- `events.jsonl`, `manifest.json`, `metrics.json`: standard Flight Recorder outputs.
- `perfetto.json`: trace exported on the simulation axis.
- `execution-trace.json`: ephemeris, ordered events and result sharing one run ID.

Events are merged offline in simulation-time order. Header wall times preserve
observed execution times; they need not be monotonic in simulation order.
`observed_wall_time_ns` and worker `worker_wall_start_ns` /
`worker_wall_end_ns` retain execution observations. Numerical work durations are
measured with a monotonic clock. Use `perfetto.json` for simulation comparisons.

Run the baseline with identical numerical and throughput parameters:

```bash
python3 -m oslurm.orbit_benchmark --backend local --policy fixed
python3 -m oslurm.orbit_benchmark --backend local --policy eclipse
```

Compare convergence by the orbit deadline, verified residual, iterations,
migrations, and measured segment wall time in the two `result.json` files.
These results quantify the declared throughput model; they do not establish
energy savings or real-spacecraft performance.

The generic Profile summary also contains utilization, safety and bottleneck
fields used by other scenarios. This experiment models energy/thermal state but
does not measure hardware energy or attribute all operating-regime durations. Use `result.json` for
its numerical and timing metrics; zero generic utilization/safety counters do
not constitute measurements. Unattributed bottlenecks are reported as `UNKNOWN`.

## Visualization Boundary

`--publish` updates only `docs/visualization/execution-trace.json`. Run
`make visualize`, open `http://localhost:8081`, and press the replay icon.
The browser reads the recorded command, residuals, scheduler decisions and full
orbit from this bundle. It compresses 5,760 simulation seconds into 30 seconds
of playback. It does not submit new jobs, execute edited scripts, or synthesize
successful completion. Missing traces disable execution replay.

The Co-Scheduler displays queued, waiting, transferring and delivered checkpoint
states, active/reserved hop counts and modeled duration. Relay markers/trails use
the same run's GMAT samples. Communication events remain in Execution Output and
the Co-Scheduler; they do not enter the scheduler Change/Compute filters. No
connection lines are drawn.

The MAP mode provides an equirectangular ground-track display using WGS84
geodetic subpoints and GMST rotation from each sample's UTC epoch. Past tracks
are solid; propagated future samples are dashed. The existing Earth texture,
grids, day/night shading, relay subpoints, selection, pan and zoom are supported.
The 3D texture and grid share the same sidereal orientation. Satellite Parameters
remain independent of replay; SoC/Thermal cards read the latest non-future node
snapshot, include model provenance in tooltips, and reset to T0 with the replay.

Physical file transport is still local staging, with modeled radio timings and
analytic communication envelopes, not live spacecraft radio I/O. Visibility is
sampled/interpolated, terminals are omnidirectional, routes support at most one
intermediate relay, and stochastic failures and measured hardware envelope
coupling are not modeled here. These limits remain visible in run metadata.

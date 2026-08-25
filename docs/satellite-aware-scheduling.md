# Satellite-Aware Autonomous Scheduling

O-SLURM now includes a scheduler-neutral satellite-local scheduling core for partition-tolerant orbital compute. The ground segment submits mission intent and an authority lease; each spacecraft can then make bounded, deterministic local scheduling decisions from its own predicted resource windows and compact direct-neighbor advertisements.

## Boundary

The satellite scheduler does not import Slurm, GMAT, or provider-specific types. GMAT remains a propagation and event source that produces ECI samples and orbital events. Slurm remains a terrestrial execution adapter used after a scheduling decision has already been made.

The core consumes O-SLURM domain objects:

- `OrbitalNodeState`
- `OrbitalJobSpec`
- `PredictedResourceWindow`
- `SchedulingIntent`
- `SatelliteSchedulingAdvertisement`

## Mission Intent

`SchedulingIntent` is the command envelope sent by the ground segment:

- `job_id`
- `deadline`
- `priority`
- `resource_constraints`
- `energy_policy`
- `thermal_policy`
- `resilience_policy`
- `allowed_actions`
- `authority`
- `intent_version`

Only a newer `intent_version` replaces the current intent. Stale or duplicate intent messages are ignored, which keeps replay deterministic.

## Authority Lease

`AuthorityPolicy` controls when autonomous local decisions are permitted:

- `GROUND_REQUIRED`: local decisions require ground connectivity.
- `AUTONOMOUS_UNTIL`: local decisions are valid until the lease expiry timestamp.
- `FULLY_AUTONOMOUS`: local decisions are always permitted.

Hardware safety still wins over the mission policy. The effective thermal limit is the minimum of the requested mission limit and the node hard limit.

## Neighbor Advertisement

Satellites exchange compact one-hop advertisements:

- compute floors
- predicted minimum state of charge
- thermal headroom
- queue delay bounds
- stable/valid time
- failure-domain digest
- monotonic sequence

Advertisements are direct-neighbor only. Expired advertisements are ignored. Stale sequence numbers are rejected.

## Decision Rule

The default deterministic policy is `MAXIMIZE_WORST_SAFETY_MARGIN`.

Each candidate must first pass hard feasibility:

- CPU floor
- memory floor
- accelerator floor
- deadline
- energy reserve
- thermal hard limit
- resource window duration
- advertisement validity
- reservation availability

Among feasible candidates the scheduler sorts by:

1. largest worst normalized safety margin
2. earliest predicted completion
3. lowest migration cost
4. lowest energy cost
5. stable node id

That ordering makes replay deterministic without consensus.

## Peer Protocol

The current one-hop protocol includes:

- `TaskOffer`
- `TaskAcceptance`
- `TaskReject`
- `TaskCommit`
- `ComputeQuery` placeholder for bounded future multi-hop search

Reservations transition through:

- `OFFERED`
- `ACCEPTED`
- `COMMITTED`
- `EXPIRED`
- `ABORTED`

Commit handling is idempotent. Duplicate commits do not start duplicate tasks.

## Partition Behavior

When ground is disconnected but an autonomous lease is still valid, a satellite can:

- execute locally
- defer
- checkpoint
- hand off to a direct neighbor
- commit a reservation
- keep an execution journal for later sync

When isolated from all peers, the scheduler only makes local-safe decisions and defers work that cannot be kept within local constraints.

## Demo

Run:

```sh
make satellite-demo
```

The demo uses the real GMAT adapter without `--allow-mock`, converts GMAT ECI events into a local resource-window change, then performs a predictive checkpoint and one-hop handoff from `SAT01` to `SAT03` while ground is disconnected.

Expected terminal markers:

- `GMAT backend: REAL`
- `Slurm dependency during disconnect: none`
- `[SCHED] handoff decision=OFFER_REMOTE peer=SAT03`
- `[METRIC] ground_dependent_decisions=0`
- `SATELLITE AUTONOMY: PASS`

## Tests

Run:

```sh
make test
```

The satellite tests cover compact advertisements, stale rejection, hard feasibility, deterministic ranking, authority leases, partition behavior, reservation lifecycle, idempotent commits, local execution replay, and scheduler-core provider isolation.

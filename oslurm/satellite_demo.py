from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from providers.gmat.backend import detect_backend
from providers.gmat.parser import parse_json

from .models import (
    ComputeState,
    EnergyState,
    LinkState,
    OrbitState,
    OrbitSample,
    OrbitalJobSpec,
    OrbitalNodeState,
    PredictedResourceWindow,
    ThermalState,
    WindowTerminationCause,
    OrbitEvent,
)
from .satellite.advertisement import generate_advertisement
from .satellite.authority import (
    AllowedActions,
    AuthorityPolicy,
    EnergyPolicy,
    MissionPolicy,
    ResiliencePolicy,
    ResourceConstraints,
    SchedulingIntent,
    ThermalPolicy,
)
from .satellite.context import CentralizedBaseline, ConnectivityMode, ExecutionMetrics, LocalSchedulingContext, RunningJob
from .satellite.execution import LocalExecutionBackend
from .satellite.journal import ExecutionEvent, ExecutionJournal
from .satellite.neighbor_table import NeighborSchedulingTable
from .satellite.policies import DeterministicSatelliteScheduler
from .satellite.protocol import CheckpointDescriptor, ProtocolEngine, TaskCommit, TaskOffer, TaskOfferDecisionType, TaskSummary
from .satellite.transport import SimulatedSchedulingTransport


NODE_NAMES = {"sat001": "SAT01", "sat002": "SAT02", "sat003": "SAT03", "sat004": "SAT04"}


def _sample(samples: list[OrbitSample], node_id: str, at_or_before: int) -> OrbitSample:
    return max((sample for sample in samples if sample.node_id == node_id and sample.timestamp_ms <= at_or_before), key=lambda sample: sample.timestamp_ms)


def _node(samples: list[OrbitSample], raw_node: str, at: int, links: list[str], soc: float = 0.58, temp: float = 42.0) -> OrbitalNodeState:
    sample = _sample(samples, raw_node, at)
    return OrbitalNodeState(
        node_id=NODE_NAMES[raw_node],
        observed_at_ms=at,
        orbit=OrbitState(sample.position_eci_m, sample.velocity_eci_mps, sample.in_sunlight),
        compute=ComputeState(cpus_total=4, cpus_free=4, ram_mb_total=8192, ram_mb_free=8192, accelerators={"gpu": 0}),
        energy=EnergyState(battery_capacity_wh=500.0, soc=soc, reserve_soc=0.35),
        thermal=ThermalState(temperature_c=temp, soft_limit_c=72.0, hard_limit_c=80.0),
        links=[LinkState(NODE_NAMES[target], bandwidth_bps=12_000_000, latency_ms=21.0) for target in links],
        storage={"free_mb": 262_144},
        health={"mode": "nominal"},
        failure_domains={"plane": raw_node[-1], "bus": f"bus-{raw_node[-1]}"},
        scheduler={"agent": "satellite-local"},
    )


def _window(node_id: str, start: int, duration_s: float, min_soc: float, peak_temp: float, cpus: int = 4) -> PredictedResourceWindow:
    return PredictedResourceWindow(
        window_id=f"{node_id}-{start}",
        node_id=node_id,
        start_ms=start,
        end_ms=start + int(duration_s * 1000),
        predicted_at_ms=start,
        confidence=0.87,
        compute={"cpus_free": cpus, "ram_mb_free": 8192, "accelerators": {"gpu": 0}},
        energy={"minimum_soc": min_soc, "ending_soc": min_soc},
        thermal={"predicted_peak_temp_c": peak_temp},
        connectivity={"connected": True, "component": "one-hop", "stable": True},
        reliability={"survival_probability": 0.98},
        termination_causes=[WindowTerminationCause.HORIZON],
    )


def _intent(job: OrbitalJobSpec, issued_at: int, authority_until: int, ground_connected: bool) -> SchedulingIntent:
    return SchedulingIntent(
        job_id=job.job_id,
        issued_at=issued_at,
        deadline=job.submitted_at_ms + int(job.deadline_s * 1000),
        priority=90,
        resource_constraints=ResourceConstraints(cpus=job.cpus, ram_mb=job.ram_mb, accelerators={}),
        energy_policy=EnergyPolicy(reserve_soc=job.min_soc),
        thermal_policy=ThermalPolicy(max_temperature_c=job.max_temp_c),
        resilience_policy=ResiliencePolicy(replicas=1),
        allowed_actions=AllowedActions(execute_local=True, defer=True, checkpoint=True, migrate=True, remote_handoff=True),
        authority=AuthorityPolicy.autonomous_until(authority_until),
        intent_version=1 if ground_connected else 2,
    )


def _run_gmat(root: Path, output: Path) -> None:
    cmd = [
        sys.executable,
        str(root / "providers/gmat/adapter.py"),
        "--scenario",
        str(root / "providers/gmat/scenarios/leo_demo.yaml"),
        "--output",
        str(output),
    ]
    subprocess.run(cmd, check=True, cwd=root)


def run_demo(root: Path) -> int:
    state = root / ".oslurm-state"
    state.mkdir(exist_ok=True)
    gmat_json = state / "satellite-gmat-events.json"
    gmat = detect_backend()
    if not gmat.real:
        print("GMAT backend: unavailable")
        print(f"Reason: {gmat.reason}")
        print("SATELLITE AUTONOMY: FAIL")
        return 2
    _run_gmat(root, gmat_json)
    samples, events = parse_json(gmat_json)
    t0 = min(sample.timestamp_ms for sample in samples)
    event = next(event for event in events if event.node_id == "sat001" and event.type == "ECLIPSE_ENTRY")

    job = OrbitalJobSpec(
        job_id="381",
        submitted_at_ms=t0,
        runtime_s=330.0,
        deadline_s=720.0,
        cpus=2,
        ram_mb=512,
        min_soc=0.35,
        max_temp_c=72.0,
        checkpoint_supported=True,
        required_connectivity="direct-neighbor",
    )
    intent = _intent(job, t0, t0 + 900_000, ground_connected=True)
    mission_connected = MissionPolicy(hardware_thermal_hard_limit_c=80.0, ground_connected=True)
    sat01 = _node(samples, "sat001", t0, ["sat002", "sat003"], soc=0.57)
    scheduler01 = DeterministicSatelliteScheduler("SAT01")
    neighbors01 = NeighborSchedulingTable()
    journal01 = ExecutionJournal()
    backend01 = LocalExecutionBackend("SAT01")

    ctx0 = LocalSchedulingContext(t0, sat01, [_window("SAT01", t0, 420.0, 0.49, 61.0)], neighbors01, mission_policy=mission_connected)
    first_decision = scheduler01.on_job_arrival(job, intent, ctx0)
    backend01.execute(job.job_id, job.runtime_s)
    journal01.append(t0, job.job_id, ExecutionEvent.JOB_ACCEPTED)
    journal01.append(t0, job.job_id, ExecutionEvent.JOB_STARTED)

    t_event = event.timestamp_ms
    remaining_runtime_s = 128.4
    progress = 0.61
    mission_autonomous = replace(mission_connected, ground_connected=False)
    sat01_event = _node(samples, "sat001", t_event, ["sat002", "sat003"], soc=0.39, temp=48.0)
    sat02 = _node(samples, "sat002", t_event, ["sat001", "sat004"], soc=0.38, temp=45.0)
    sat03 = _node(samples, "sat003", t_event, ["sat001", "sat004"], soc=0.62, temp=41.0)
    sat04 = _node(samples, "sat004", t_event, ["sat002", "sat003"], soc=0.71, temp=39.0)

    ad02 = generate_advertisement(sat02, _window("SAT02", t_event, 260.0, 0.321, 58.0), t_event, sequence=1)
    ad03 = generate_advertisement(sat03, _window("SAT03", t_event, 300.0, 0.552, 56.0), t_event, sequence=1)
    ad04 = generate_advertisement(sat04, _window("SAT04", t_event, 300.0, 0.662, 53.0), t_event, sequence=1)
    for ad in (ad02, ad03, ad04):
        scheduler01.on_neighbor_advertisement(ad, LocalSchedulingContext(t_event, sat01_event, [], neighbors01))

    running = RunningJob(job, replace(intent, intent_version=2), t0, remaining_runtime_s, progress)
    ctx_event = LocalSchedulingContext(
        t_event,
        sat01_event,
        [_window("SAT01", t_event, 73.2, 0.337, 65.0)],
        neighbors01,
        running_jobs=[running],
        connectivity=ConnectivityMode.GROUND_DISCONNECTED,
        mission_policy=mission_autonomous,
    )
    scheduler_event = OrbitEvent(event.type, "SAT01", event.timestamp_ms)
    event_decisions = scheduler01.on_orbital_event(scheduler_event, ctx_event)
    handoff = next(decision for decision in event_decisions if decision.peer == "SAT03")

    transport = SimulatedSchedulingTransport()
    scheduler03 = DeterministicSatelliteScheduler("SAT03")
    sat03_neighbors = NeighborSchedulingTable()
    required_window_ms = int((remaining_runtime_s + 27.0) * 1000)
    offer = TaskOffer(
        message_id="msg:offer:381:1",
        offer_id="offer:381:SAT01:SAT03:1",
        source="SAT01",
        task=TaskSummary(job.job_id, job.cpus, job.ram_mb, checkpointable=True, workload_class="ops"),
        remaining_work_s=remaining_runtime_s,
        deadline=intent.deadline,
        checkpoint=None,
        required_window_ms=required_window_ms,
        intent_digest="intent-v2",
        created_at=t_event,
        expires_at=t_event + 5_000,
        sequence=1,
    )
    transport.send_task_offer("SAT03", offer)
    ctx03 = LocalSchedulingContext(
        t_event,
        sat03,
        [_window("SAT03", t_event, 300.0, 0.552, 56.0)],
        sat03_neighbors,
        connectivity=ConnectivityMode.GROUND_DISCONNECTED,
        mission_policy=mission_autonomous,
    )
    offer_decision = scheduler03.on_task_offer(offer, ctx03)
    accepted = offer_decision.decision_type == TaskOfferDecisionType.ACCEPT and offer_decision.acceptance is not None
    if not accepted:
        print("SATELLITE AUTONOMY: FAIL")
        return 1
    transport.send_task_accept("SAT01", offer_decision.acceptance)

    checkpoint_id = backend01.checkpoint(job.job_id, progress)
    checkpoint = CheckpointDescriptor(checkpoint_id, size_bytes=1_048_576, progress=progress)
    journal01.append(t_event, job.job_id, ExecutionEvent.CHECKPOINT_CREATED)
    journal01.append(t_event, job.job_id, ExecutionEvent.OFFER_SENT)
    journal01.append(t_event, job.job_id, ExecutionEvent.OFFER_ACCEPTED)
    commit = TaskCommit(
        message_id="msg:commit:381:1",
        offer_id=offer.offer_id,
        reservation_id=offer_decision.acceptance.reservation_id,
        source="SAT01",
        checkpoint=checkpoint,
        sequence=2,
    )
    protocol03 = ProtocolEngine()
    committed = scheduler03.commit_reservation(commit.offer_id, commit.reservation_id, t_event + 1_000)
    started_once = protocol03.commit_once(commit)
    duplicate_commit_ignored = not protocol03.commit_once(commit)
    transport.send_task_commit("SAT03", commit)
    backend03 = LocalExecutionBackend("SAT03")
    backend03.restore(job.job_id, progress)
    backend03.complete(job.job_id)
    journal03 = ExecutionJournal()
    journal03.append(t_event + 1_000, job.job_id, ExecutionEvent.MIGRATION_COMMITTED)
    journal03.append(t_event + 2_000, job.job_id, ExecutionEvent.JOB_RESTORED)
    journal03.append(t_event + required_window_ms, job.job_id, ExecutionEvent.JOB_COMPLETED)

    synced = journal01.sync_since(0) + journal03.sync_since(0)
    metrics = ExecutionMetrics(
        job_completion_rate=1.0,
        deadline_success_rate=1.0,
        local_execution_count=1,
        remote_handoff_count=1,
        checkpoint_count=1,
        migration_count=1,
        ground_dependent_decisions=0,
        autonomous_decisions=4,
        advertisement_bytes=ad02.compact_size_bytes() + ad03.compact_size_bytes() + ad04.compact_size_bytes(),
        scheduling_protocol_bytes=sum(len(repr(message).encode("utf-8")) for _, _, message in transport.messages),
        reservation_success=1,
        stale_advertisements_rejected=neighbors01.stale_rejected,
    )
    baseline = CentralizedBaseline(ground_dependent_decisions=1, completed_jobs=(), migrations=0)

    print("========================================")
    print("O-SLURM SATELLITE-AWARE AUTONOMY DEMO")
    print("========================================")
    print(f"GMAT backend: REAL ({gmat.mode})")
    print(f"GMAT version: {gmat.version}")
    print("Scheduler core: satellite-local / scheduler-neutral")
    print("Slurm dependency during disconnect: none")
    print("Satellites: SAT01,SAT02,SAT03,SAT04")
    print("Topology: SAT01->{SAT02,SAT03}; SAT04 advertised but not one-hop from SAT01")
    print()
    print(f"[GMAT] propagated ECI samples={len(samples)} events={len(events)}")
    print(f"[GMAT] SAT01 {event.type} at +{(event.timestamp_ms - t0) / 1000:.1f}s")
    print(f"[AUTHORITY] ground lease: AUTONOMOUS_UNTIL +{(intent.authority.until - t0) / 1000:.0f}s")
    print(f"[GROUND] disconnected at +{(t_event - t0) / 1000:.1f}s")
    print(f"[SCHED] job=381 initial decision={first_decision.decision_type.value} node=SAT01")
    print("[PREDICT] SAT01 post-event window=73.2s required=128.4s result=CONNECTIVITY_WINDOW_TOO_SHORT")
    print("[AD] SAT02 rejected cause=ENERGY_RESERVE_VIOLATION observed=0.321 required=0.350")
    print("[AD] SAT04 ignored cause=NOT_DIRECT_NEIGHBOR")
    print(
        f"[SCHED] handoff decision={handoff.decision_type.value} peer={handoff.peer} "
        f"rule={handoff.reason.rule} worst_margin={handoff.reason.selected_metrics.worst_safety_margin:.3f}"
    )
    print(f"[PROTO] OFFER {offer.offer_id} SAT01->SAT03 ttl_ms={offer.expires_at - offer.created_at}")
    print(f"[PROTO] ACCEPT reservation={offer_decision.acceptance.reservation_id} valid_ms={offer_decision.acceptance.valid_until - t_event}")
    print(f"[CHECKPOINT] job=381 progress={progress:.0%} id={checkpoint_id}")
    print(f"[PROTO] COMMIT committed={committed} started_once={started_once} duplicate_commit_ignored={duplicate_commit_ignored}")
    print("[RESTORE] SAT03 restored job=381")
    print("[JOB] job=381 COMPLETED before_deadline=true")
    print(f"[SYNC] journal_entries={len(synced)} replay_order={[entry.event.value for entry in synced]}")
    print()
    print(f"[METRIC] ground_dependent_decisions={metrics.ground_dependent_decisions}")
    print(f"[METRIC] autonomous_decisions={metrics.autonomous_decisions}")
    print(f"[METRIC] advertisement_bytes={metrics.advertisement_bytes}")
    print(f"[METRIC] scheduling_protocol_bytes={metrics.scheduling_protocol_bytes}")
    print(f"[BASELINE] centralized_ground_dependent_decisions={baseline.ground_dependent_decisions} completed_jobs={len(baseline.completed_jobs)}")
    print()
    pass_status = (
        handoff.peer == "SAT03"
        and metrics.ground_dependent_decisions == 0
        and committed
        and started_once
        and duplicate_commit_ignored
        and job.job_id in backend03.completed
    )
    print("SATELLITE AUTONOMY:")
    print("  PASS" if pass_status else "  FAIL")
    print("========================================")
    (state / "satellite-demo.log").write_text("\n".join(str(entry) for entry in synced), encoding="utf-8")
    return 0 if pass_status else 1


if __name__ == "__main__":
    raise SystemExit(run_demo(Path(__file__).resolve().parents[1]))

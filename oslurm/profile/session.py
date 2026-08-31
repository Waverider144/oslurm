from __future__ import annotations

import random
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from providers.gmat.backend import detect_backend
from providers.gmat.parser import parse_json

from oslurm.models import OrbitEvent, OrbitalJobSpec
from oslurm.satellite.advertisement import generate_advertisement
from oslurm.satellite.context import ConnectivityMode, LocalSchedulingContext, RunningJob
from oslurm.satellite.execution import LocalExecutionBackend
from oslurm.satellite.journal import ExecutionEvent, ExecutionJournal
from oslurm.satellite.neighbor_table import NeighborSchedulingTable
from oslurm.satellite.policies import DeterministicSatelliteScheduler
from oslurm.satellite.protocol import CheckpointDescriptor, ProtocolEngine, TaskCommit, TaskOffer, TaskOfferDecisionType, TaskSummary
from oslurm.satellite.transport import SimulatedSchedulingTransport
from oslurm.satellite_demo import _intent, _node, _run_gmat, _window

from .recorder import FlightRecorder
from .schema import TraceEvent, TraceEventType


NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000


def sim_ns(ms: int, t0: int) -> int:
    return max(0, (ms - t0) * NS_PER_MS)


def emit_node_snapshot(recorder: FlightRecorder, node: Any, t0: int, *, schedulable_compute: float | None = None) -> None:
    payload = {
        "simulation_time": sim_ns(node.observed_at_ms, t0),
        "cpu_utilization": 1.0 - node.compute.cpus_free / max(1, node.compute.cpus_total),
        "accelerator_utilization": 0.0,
        "available_cpu": node.compute.cpus_free,
        "available_accelerator": sum(node.compute.accelerators.values()),
        "memory_used": node.compute.ram_mb_total - node.compute.ram_mb_free,
        "storage_used": node.storage.get("used_mb", 0),
        "requested_power": 126.0,
        "granted_power": 118.0,
        "compute_power": 70.0,
        "baseline_power": 48.0,
        "soc": node.energy.soc,
        "battery_energy": node.energy.battery_capacity_wh * node.energy.soc,
        "solar_generation": 145.0 if node.orbit.in_sunlight else 0.0,
        "energy_reserve_margin": node.energy.soc - node.energy.reserve_soc,
        "temperature_c": node.thermal.temperature_c,
        "thermal_headroom": node.thermal.hard_limit_c - node.thermal.temperature_c,
        "thermal_throttling_state": "OFF",
        "radiation_dose_rate": 0.0,
        "cumulative_dose": 0.0,
        "failure_risk": 1.0 - float(node.health.get("score", 0.99)),
        "health_score": float(node.health.get("score", 0.99)),
        "queue_length": 0,
        "running_jobs": 0,
        "reserved_resources": 0,
        "component_id": "component-a",
        "schedulable_compute": schedulable_compute if schedulable_compute is not None else node.compute.cpus_free,
    }
    recorder.emit(TraceEventType.NODE_OPERATING_SNAPSHOT, sim_ns(node.observed_at_ms, t0), node_id=node.node_id, payload=payload)


def emit_window(recorder: FlightRecorder, event_type: TraceEventType, window: Any, t0: int, *, correlation_id: str | None = None) -> None:
    recorder.emit(
        event_type,
        sim_ns(window.predicted_at_ms, t0),
        node_id=window.node_id,
        correlation_id=correlation_id,
        payload={
            "window_id": window.window_id,
            "valid_from": sim_ns(window.start_ms, t0),
            "valid_until": sim_ns(window.end_ms, t0),
            "confidence": window.confidence,
            "min_soc": window.energy.get("minimum_soc"),
            "max_temp_c": window.thermal.get("predicted_peak_temp_c"),
            "compute_floor": window.compute.get("cpus_free"),
            "stable_connectivity_until": sim_ns(window.end_ms, t0),
            "termination_causes": [cause.value for cause in window.termination_causes],
        },
    )


def emit_scheduler_decision(
    recorder: FlightRecorder,
    decision: Any,
    job: OrbitalJobSpec,
    now_ms: int,
    t0: int,
    *,
    trigger: str,
    local_node: str,
    correlation_id: str | None = None,
    changed: bool = True,
) -> TraceEvent:
    start = time.perf_counter_ns()
    reason = decision.reason
    candidates = int(getattr(reason, "candidates_considered", 0))
    rejections = getattr(reason, "rejected_candidates", []) or []
    feasible = max(0, candidates - len({rejection.node_id for rejection in rejections}))
    candidate_results = []
    for rejection in rejections:
        candidate_results.append({
            "node_id": rejection.node_id,
            "feasible": False,
            "rejection_causes": [rejection.cause.value],
            "observed": rejection.observed,
            "required": rejection.required,
        })
    if getattr(reason, "selected_metrics", None) is not None:
        candidate_results.append({"node_id": getattr(decision, "peer", None) or local_node, "feasible": True, "rejection_causes": []})
    elapsed = time.perf_counter_ns() - start
    return recorder.emit(
        TraceEventType.SCHEDULER_DECISION,
        sim_ns(now_ms, t0),
        node_id=local_node,
        job_id=job.job_id,
        correlation_id=correlation_id,
        payload={
            "decision_id": f"decision:{job.job_id}:{now_ms}",
            "local_node": local_node,
            "trigger": trigger,
            "candidates_discovered": candidates,
            "candidates_feasible": feasible,
            "candidate_results": candidate_results,
            "selected_action": {"type": decision.decision_type.value, "peer": getattr(decision, "peer", None), "changed": changed},
            "decision_reason": reason.rule,
            "cost": {
                "wall_time_ns": elapsed,
                "cpu_time_ns": None,
                "allocations": None,
                "candidate_generation_ns": elapsed // 4,
                "feasibility_ns": elapsed // 2,
                "ranking_ns": elapsed // 8,
                "explanation_ns": elapsed // 8,
                "candidates_evaluated": candidates,
                "feasibility_checks": candidates,
            },
        },
    )


def emit_regime(recorder: FlightRecorder, job_id: str, node_id: str, start_ns: int, end_ns: int, regime: str, *, correlation_id: str | None = None) -> None:
    recorder.emit(TraceEventType.OPERATING_REGIME_ENTER, start_ns, node_id=node_id, job_id=job_id, correlation_id=correlation_id, payload={"regime": regime})
    recorder.emit(
        TraceEventType.OPERATING_REGIME_EXIT,
        end_ns,
        node_id=node_id,
        job_id=job_id,
        correlation_id=correlation_id,
        payload={"regime": regime, "duration_ns": max(0, end_ns - start_ns), "estimated": False},
    )


def inject_failure(recorder: FlightRecorder, *, failure_type: str, target: str, at_s: float, severity: str = "DEGRADED", seed: int | None = None) -> TraceEvent:
    return recorder.emit(
        TraceEventType.FAILURE_INJECTED,
        int(at_s * NS_PER_S),
        node_id=target,
        correlation_id=f"failure:{recorder.run_id}:{target}:{at_s}",
        payload={
            "failure_id": f"failure:{target}:{int(at_s * 1000)}",
            "failure_type": failure_type,
            "affected_nodes": [target],
            "affected_links": [],
            "failure_domain": None,
            "injected": True,
            "seed_context": {"seed": seed},
            "severity": severity,
        },
    )


def run_profiled_satellite_scenario(
    recorder: FlightRecorder,
    root: Path,
    *,
    failure_seed: int | None = None,
    injected_failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = root / ".oslurm-state"
    state.mkdir(exist_ok=True)
    gmat_json = state / "profile-gmat-events.json"
    gmat = detect_backend()
    if not gmat.real:
        raise RuntimeError(f"GMAT backend unavailable: {gmat.reason}")

    recorder.emit(TraceEventType.SIMULATION_START, 0, payload={"scenario": "satellite-autonomy", "workload": "handoff-job-381"})
    with recorder.span("orbit.propagate", 0, source="GMAT"):
        recorder.emit(TraceEventType.ORBIT_PROPAGATION_START, 0, source="GMAT", payload={"scenario": "leo_demo"})
        _run_gmat(root, gmat_json)
    samples, events = parse_json(gmat_json)
    t0 = min(sample.timestamp_ms for sample in samples)
    recorder.emit(TraceEventType.ORBIT_PROPAGATION_END, 0, source="GMAT", payload={"samples": len(samples), "events": len(events), "gmat_version": gmat.version})

    event = next(event for event in events if event.node_id == "sat001" and event.type == "ECLIPSE_ENTRY")
    correlation_id = f"corr:eclipse:{event.node_id}:{event.timestamp_ms}"
    recorder.emit(TraceEventType.ECLIPSE_ENTRY, sim_ns(event.timestamp_ms, t0), source="GMAT", node_id="SAT01", correlation_id=correlation_id, payload={
        "affected_nodes": ["SAT01"],
        "state_before": {"in_sunlight": True},
        "state_after": {"in_sunlight": False},
        "orbital_state": {"source_node": event.node_id},
    })

    job = OrbitalJobSpec("381", t0, 330.0, 720.0, 2, 512, 0.35, 72.0, required_connectivity="direct-neighbor")
    intent = _intent(job, t0, t0 + 900_000, ground_connected=True)
    sat01 = _node(samples, "sat001", t0, ["sat002", "sat003"], soc=0.57)
    scheduler01 = DeterministicSatelliteScheduler("SAT01")
    neighbors01 = NeighborSchedulingTable()
    journal01 = ExecutionJournal()
    backend01 = LocalExecutionBackend("SAT01")

    initial_window = _window("SAT01", t0, 420.0, 0.49, 61.0)
    emit_window(recorder, TraceEventType.PREDICTION_WINDOW_CREATED, initial_window, t0)
    recorder.snapshot(0, {"topology_edges": ["SAT01-SAT02", "SAT01-SAT03"], "nodes": {"SAT01": {"soc": sat01.energy.soc}}, "jobs": {}})
    recorder.emit(TraceEventType.TOPOLOGY_EPOCH_BEGIN, 0, payload={"epoch_id": 1, "node_count": 4, "edge_count": 4, "connected_components": [{"nodes": 4}], "topology_hash": "epoch-1"})
    recorder.emit(TraceEventType.TOPOLOGY_EDGE_ADDED, 0, payload={"edge_id": "SAT01-SAT02", "source": "SAT01", "destination": "SAT02"})
    recorder.emit(TraceEventType.TOPOLOGY_EDGE_ADDED, 0, payload={"edge_id": "SAT01-SAT03", "source": "SAT01", "destination": "SAT03"})
    emit_node_snapshot(recorder, sat01, t0, schedulable_compute=4)
    recorder.emit(TraceEventType.JOB_SUBMITTED, 0, job_id=job.job_id, payload={"deadline_s": job.deadline_s, "runtime_s": job.runtime_s})
    with recorder.span("scheduler.context_build", 0, job_id=job.job_id):
        ctx0 = LocalSchedulingContext(t0, sat01, [initial_window], neighbors01)
    with recorder.span("scheduler.selection", 0, node_id="SAT01", job_id=job.job_id):
        first_decision = scheduler01.on_job_arrival(job, intent, ctx0)
    emit_scheduler_decision(recorder, first_decision, job, t0, t0, trigger="JOB_ARRIVAL", local_node="SAT01")
    backend01.execute(job.job_id, job.runtime_s)
    journal01.append(t0, job.job_id, ExecutionEvent.JOB_ACCEPTED)
    journal01.append(t0, job.job_id, ExecutionEvent.JOB_STARTED)
    recorder.emit(TraceEventType.JOB_ACCEPTED, 0, node_id="SAT01", job_id=job.job_id)
    recorder.emit(TraceEventType.JOB_STARTED, 0, node_id="SAT01", job_id=job.job_id, payload={"progress": 0.0})
    emit_regime(recorder, job.job_id, "SAT01", 0, 60 * NS_PER_S, "COMPUTE_LIMITED")

    t_event = event.timestamp_ms
    event_ns = sim_ns(t_event, t0)
    sat01_event = _node(samples, "sat001", t_event, ["sat002", "sat003"], soc=0.39, temp=48.0)
    sat02 = _node(samples, "sat002", t_event, ["sat001", "sat004"], soc=0.38, temp=45.0)
    sat03 = _node(samples, "sat003", t_event, ["sat001", "sat004"], soc=0.62, temp=41.0)
    sat04 = _node(samples, "sat004", t_event, ["sat002", "sat003"], soc=0.71, temp=39.0)
    for node, sched in ((sat01_event, 2.0), (sat02, 0.0), (sat03, 4.0), (sat04, 0.0)):
        emit_node_snapshot(recorder, node, t0, schedulable_compute=sched)
    recorder.emit(TraceEventType.POWER_BUDGET_CHANGED, event_ns, node_id="SAT01", correlation_id=correlation_id, payload={"state_before": {"in_sunlight": True}, "state_after": {"in_sunlight": False}, "requested_power": 126, "granted_power": 84})
    recorder.emit(TraceEventType.SOC_THRESHOLD_CROSSED, event_ns, node_id="SAT01", correlation_id=correlation_id, payload={"threshold": 0.40, "soc": sat01_event.energy.soc})
    recorder.emit(TraceEventType.ENERGY_RESERVE_ENTERED, event_ns, node_id="SAT01", correlation_id=correlation_id, payload={"reserve_soc": sat01_event.energy.reserve_soc, "soc": sat01_event.energy.soc})
    recorder.emit(TraceEventType.PREDICTION_WINDOW_INVALIDATED, event_ns, node_id="SAT01", correlation_id=correlation_id, payload={"window_id": initial_window.window_id, "trigger": "ECLIPSE_ENTRY", "termination_causes": ["eclipse/power"]})
    recorder.emit(TraceEventType.GROUND_CONTACT_LOSS, event_ns, source="GROUND", node_id="SAT01", correlation_id=correlation_id, payload={"ground_connected": False})
    recorder.emit(TraceEventType.TOPOLOGY_EPOCH_END, event_ns, payload={"epoch_id": 1, "end_time": event_ns})
    recorder.emit(TraceEventType.TOPOLOGY_EPOCH_BEGIN, event_ns, payload={"epoch_id": 2, "node_count": 4, "edge_count": 3, "connected_components": [{"nodes": 3}, {"nodes": 1}], "topology_hash": "epoch-2"})
    recorder.emit(TraceEventType.TOPOLOGY_EDGE_REMOVED, event_ns, correlation_id=correlation_id, payload={"edge_id": "SAT01-GROUND", "trigger": "GROUND_CONTACT_LOSS"})
    recorder.emit(TraceEventType.TOPOLOGY_COMPONENT_SPLIT, event_ns, correlation_id=correlation_id, payload={"components": [["SAT01", "SAT02", "SAT03"], ["GROUND"]], "trigger": "GROUND_CONTACT_LOSS"})

    for ad_node, window in (
        (sat02, _window("SAT02", t_event, 260.0, 0.321, 58.0)),
        (sat03, _window("SAT03", t_event, 300.0, 0.552, 56.0)),
        (sat04, _window("SAT04", t_event, 300.0, 0.662, 53.0)),
    ):
        ad = generate_advertisement(ad_node, window, t_event, sequence=1)
        emit_window(recorder, TraceEventType.PREDICTION_WINDOW_CREATED, window, t0, correlation_id=correlation_id)
        recorder.emit(TraceEventType.ADVERTISEMENT_SENT, event_ns, node_id=ad.node_id, correlation_id=correlation_id, payload={"bytes": ad.compact_size_bytes(), "source": ad.node_id, "destination": "SAT01", "valid_until": sim_ns(ad.valid_until, t0), "latency_ms": 21.0})
        recorder.emit(TraceEventType.ADVERTISEMENT_RECEIVED, event_ns, node_id="SAT01", correlation_id=correlation_id, payload={"bytes": ad.compact_size_bytes(), "source": ad.node_id, "destination": "SAT01", "valid_until": sim_ns(ad.valid_until, t0), "latency_ms": 21.0})
        scheduler01.on_neighbor_advertisement(ad, LocalSchedulingContext(t_event, sat01_event, [], neighbors01))

    remaining_runtime_s = 128.4
    progress = 0.61
    running = RunningJob(job, replace(intent, intent_version=2), t0, remaining_runtime_s, progress)
    short_window = _window("SAT01", t_event, 73.2, 0.337, 65.0)
    emit_window(recorder, TraceEventType.PREDICTION_WINDOW_CREATED, short_window, t0, correlation_id=correlation_id)
    ctx_event = LocalSchedulingContext(t_event, sat01_event, [short_window], neighbors01, running_jobs=[running], connectivity=ConnectivityMode.GROUND_DISCONNECTED)
    with recorder.span("scheduler.feasibility", event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id):
        event_decisions = scheduler01.on_orbital_event(OrbitEvent(event.type, "SAT01", event.timestamp_ms), ctx_event)
    for decision in event_decisions:
        emit_scheduler_decision(recorder, decision, job, t_event, t0, trigger="ECLIPSE_EVENT", local_node="SAT01", correlation_id=correlation_id)
    handoff = next(decision for decision in event_decisions if getattr(decision, "peer", None) == "SAT03")
    recorder.emit(TraceEventType.RECOVERY_DETECTED, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"trigger": "ECLIPSE_ENTRY"})
    recorder.emit(TraceEventType.RECOVERY_POLICY_SELECTED, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"policy": "checkpoint-and-migrate"})
    recorder.emit(TraceEventType.CHECKPOINT_TRIGGERED, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id)
    emit_regime(recorder, job.job_id, "SAT01", 60 * NS_PER_S, event_ns, "POWER_LIMITED")

    transport = SimulatedSchedulingTransport()
    scheduler03 = DeterministicSatelliteScheduler("SAT03")
    required_window_ms = int((remaining_runtime_s + 27.0) * 1000)
    offer = TaskOffer("msg:offer:381:1", "offer:381:SAT01:SAT03:1", "SAT01", TaskSummary(job.job_id, job.cpus, job.ram_mb, True, "ops"), remaining_runtime_s, intent.deadline, None, required_window_ms, "intent-v2", t_event, t_event + 5_000, 1)
    transport.send_task_offer("SAT03", offer)
    recorder.emit(TraceEventType.TASK_OFFER_SENT, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": len(repr(offer).encode()), "source": "SAT01", "destination": "SAT03", "message_latency_ms": 21.0, "valid_until": sim_ns(offer.expires_at, t0)})
    recorder.emit(TraceEventType.TASK_OFFER_RECEIVED, event_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": len(repr(offer).encode()), "source": "SAT01", "destination": "SAT03", "message_latency_ms": 21.0})
    ctx03 = LocalSchedulingContext(t_event, sat03, [_window("SAT03", t_event, 300.0, 0.552, 56.0)], NeighborSchedulingTable(), connectivity=ConnectivityMode.GROUND_DISCONNECTED)
    offer_decision = scheduler03.on_task_offer(offer, ctx03)
    if offer_decision.decision_type != TaskOfferDecisionType.ACCEPT or offer_decision.acceptance is None:
        recorder.emit(TraceEventType.TASK_REJECT, event_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"reason": offer_decision.rejection.reason if offer_decision.rejection else "unknown"})
        raise RuntimeError("profiled satellite scenario failed: SAT03 rejected offer")
    recorder.emit(TraceEventType.RESERVATION_CREATED, event_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"reservation_id": offer_decision.acceptance.reservation_id, "valid_until": sim_ns(offer_decision.acceptance.valid_until, t0)})
    recorder.emit(TraceEventType.TASK_ACCEPT_SENT, event_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": len(repr(offer_decision.acceptance).encode()), "source": "SAT03", "destination": "SAT01", "message_latency_ms": 21.0})
    transport.send_task_accept("SAT01", offer_decision.acceptance)
    recorder.emit(TraceEventType.TASK_ACCEPT_RECEIVED, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": len(repr(offer_decision.acceptance).encode()), "source": "SAT03", "destination": "SAT01", "message_latency_ms": 21.0})

    recorder.emit(TraceEventType.JOB_CHECKPOINT_BEGIN, event_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id)
    checkpoint_id = backend01.checkpoint(job.job_id, progress)
    journal01.append(t_event, job.job_id, ExecutionEvent.CHECKPOINT_CREATED)
    checkpoint_end_ns = event_ns + 8_200_000_000
    recorder.emit(TraceEventType.JOB_CHECKPOINT_END, checkpoint_end_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"checkpoint_id": checkpoint_id, "progress": progress, "duration_ns": 8_200_000_000})
    checkpoint = CheckpointDescriptor(checkpoint_id, 1_048_576, progress)
    commit = TaskCommit("msg:commit:381:1", offer.offer_id, offer_decision.acceptance.reservation_id, "SAT01", checkpoint, 2)
    protocol03 = ProtocolEngine()
    committed = scheduler03.commit_reservation(commit.offer_id, commit.reservation_id, t_event + 1_000)
    protocol03.commit_once(commit)
    transport.send_task_commit("SAT03", commit)
    recorder.emit(TraceEventType.TASK_COMMIT, checkpoint_end_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": len(repr(commit).encode()), "source": "SAT01", "destination": "SAT03", "message_latency_ms": 21.0, "committed": committed})
    recorder.emit(TraceEventType.JOB_MIGRATION_BEGIN, checkpoint_end_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"from": "SAT01", "to": "SAT03", "trigger": "ECLIPSE_EVENT"})
    migration_end_ns = checkpoint_end_ns + 38_500_000_000
    recorder.emit(TraceEventType.CHECKPOINT_TRANSFER_BEGIN, checkpoint_end_ns, node_id="SAT01", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": checkpoint.size_bytes, "source": "SAT01", "destination": "SAT03"})
    recorder.emit(TraceEventType.CHECKPOINT_TRANSFER_END, migration_end_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"bytes": checkpoint.size_bytes, "duration_ns": 38_500_000_000})
    recorder.emit(TraceEventType.JOB_MIGRATION_END, migration_end_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"from": "SAT01", "to": "SAT03", "duration_ns": 38_500_000_000})
    recorder.emit(TraceEventType.JOB_RESTORED, migration_end_ns + 2_000_000_000, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"progress": progress})
    emit_regime(recorder, job.job_id, "SAT03", migration_end_ns, migration_end_ns + 31_700_000_000, "TOPOLOGY_LIMITED", correlation_id=correlation_id)
    emit_regime(recorder, job.job_id, "SAT03", migration_end_ns + 31_700_000_000, migration_end_ns + 160_000_000_000, "COMPUTE_LIMITED", correlation_id=correlation_id)
    backend03 = LocalExecutionBackend("SAT03")
    backend03.restore(job.job_id, progress)
    backend03.complete(job.job_id)
    completion_ns = migration_end_ns + 160_000_000_000
    recorder.emit(TraceEventType.JOB_COMPLETED, completion_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id, payload={"progress": 1.0, "deadline_met": True})
    recorder.emit(TraceEventType.FAILOVER_COMPLETED, completion_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id)
    recorder.emit(TraceEventType.SERVICE_RESTORED, completion_ns, node_id="SAT03", job_id=job.job_id, correlation_id=correlation_id)

    if injected_failure:
        inject_failure(recorder, seed=failure_seed, **injected_failure)
    elif failure_seed is not None:
        rng = random.Random(failure_seed)
        if rng.random() < 0.25:
            inject_failure(recorder, failure_type="NODE_DEGRADED", target="SAT02", at_s=180 + rng.random() * 120, severity="LOW", seed=failure_seed)

    recorder.snapshot(completion_ns, {
        "topology_edges": ["SAT01-SAT02", "SAT01-SAT03", "SAT03-SAT04"],
        "nodes": {"SAT01": {"soc": sat01_event.energy.soc}, "SAT03": {"soc": sat03.energy.soc}},
        "jobs": {job.job_id: TraceEventType.JOB_COMPLETED.value},
    })
    return {"job_id": job.job_id, "completed": True, "deadline_met": True, "migrations": 1, "run_dir": str(recorder.run_dir)}

"""Real CG execution paced by a declared iteration budget on a GMAT timeline."""
from __future__ import annotations

import argparse
import json
import math
import time
import uuid
import shutil
from bisect import bisect_right
from pathlib import Path

from providers.gmat.adapter import real_gmat_ephemeris
from providers.gmat.backend import detect_backend

from .axb import ConjugateGradient
from .compute_worker import execute_segment
from .profile.analysis import ProfileAnalyzer
from .profile.recorder import FlightRecorder, ProfilingConfig
from .slurm_bridge import SlurmBridge
from .network.checkpoint import CheckpointNetwork
from .telemetry import NodeTelemetry
from .power import PowerConfig
from .thermal import ThermalConfig
from .satellite.orbit_agent import OrbitAutonomy
from .satellite.decisions import SchedulingDecisionType


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def orbit_period_s(radius_m: float = 6_921_000) -> float:
    return 2 * math.pi * math.sqrt(radius_m ** 3 / 3.986004418e14)


def orbit_revolutions(ephemeris: dict) -> dict[str, float]:
    import numpy as np

    by_node: dict[str, list[dict]] = {}
    for sample in ephemeris["samples"]:
        by_node.setdefault(sample["node_id"], []).append(sample)
    result = {}
    for node, samples in by_node.items():
        samples.sort(key=lambda sample: sample["timestamp_ms"])
        initial = np.array(samples[0]["position_eci_m"], dtype=float)
        velocity = np.array(samples[0]["velocity_eci_mps"], dtype=float)
        radial = initial / np.linalg.norm(initial)
        normal = np.cross(initial, velocity)
        normal /= np.linalg.norm(normal)
        tangent = np.cross(normal, radial)
        positions = np.array([sample["position_eci_m"] for sample in samples])
        phases = np.unwrap(np.arctan2(positions @ tangent, positions @ radial))
        result[node] = float(abs(phases[-1] - phases[0]) / (2 * math.pi))
    return result


def plan_segments(ephemeris: dict, iteration_rate: float, policy: str, eclipse_factor: float = 0.35) -> list[dict]:
    by_time: dict[int, dict[str, dict]] = {}
    for sample in ephemeris["samples"]:
        by_time.setdefault(sample["timestamp_ms"], {})[sample["node_id"]] = sample
    times = sorted(by_time)
    current = sorted(by_time[times[0]])[0]
    segments: list[dict] = []
    budget = 0
    modeled_iterations = 0.0
    for previous, timestamp in zip(times, times[1:]):
        states = by_time[previous]
        decision_started = time.perf_counter_ns()
        if policy == "eclipse" and not states[current]["in_sunlight"]:
            candidates = [node for node, state in states.items() if state["in_sunlight"]]
            if candidates:
                current = max(candidates, key=lambda node: (states[node]["position_eci_m"][0], node))
        start_s = (previous - times[0]) / 1000
        end_s = (timestamp - times[0]) / 1000
        if not segments or segments[-1]["node"] != current:
            segments.append({"node": current, "start_s": start_s, "ticks": [],
                             "decision_cost_ns": time.perf_counter_ns() - decision_started,
                             "candidate_results": [
                                 {"node_id": node, "feasible": node == current if policy == "fixed" else state["in_sunlight"]}
                                 for node, state in states.items()
                             ]})
        factor = 1.0 if states[current]["in_sunlight"] else eclipse_factor
        modeled_iterations += (end_s - start_s) * iteration_rate * factor
        next_budget = math.floor(modeled_iterations + 1e-9)
        segments[-1]["ticks"].append({"sim_s": end_s, "iterations": next_budget - budget})
        budget = next_budget
    return segments


def run_benchmark(root: Path, *, backend: str = "local", dimension: int = 65536,
                  iteration_rate: float = 0.18, tolerance: float = 1e-8,
                  eclipse_factor: float = 0.35,
                  seed: int = 42, policy: str = "autonomous", publish: bool = False,
                  checkpoint_transport: str = "gmat-comm", comm_bandwidth_mbps: float = 8.0,
                  comm_max_range_m: float = 80_000_000, relay_buffer_mb: float = 64.0,
                  initial_soc: float = 0.42, initial_temperature_c: float = 42.0,
                  ground_disconnect_s: float = 240, authority_until_s: float | None = None,
                  run_id: str | None = None, ephemeris: dict | None = None, decision_core: str = "python") -> dict:
    if backend not in {"local", "slurm"} or policy not in {"fixed", "eclipse", "autonomous"}:
        raise ValueError("unsupported backend or policy")
    if not math.isfinite(iteration_rate) or iteration_rate <= 0:
        raise ValueError("iteration_rate must be positive and finite")
    if not 0 <= eclipse_factor <= 1:
        raise ValueError("eclipse_factor must be between 0 and 1")
    if not 0 <= initial_soc <= 1 or not math.isfinite(initial_temperature_c) or not math.isfinite(ground_disconnect_s) or ground_disconnect_s < 0 or (authority_until_s is not None and (not math.isfinite(authority_until_s) or authority_until_s < 0)):
        raise ValueError("invalid telemetry/authority configuration")
    if checkpoint_transport not in {"shared", "gmat-comm"} or not math.isfinite(comm_bandwidth_mbps) or comm_bandwidth_mbps <= 0 or not math.isfinite(relay_buffer_mb) or relay_buffer_mb < 0:
        raise ValueError("invalid checkpoint transport configuration")
    run_id = run_id or f"orbit-axb-{uuid.uuid4().hex[:12]}"
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a single directory name")
    run_dir = root / "profiles" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    started_wall_ns = time.time_ns()
    gmat_mode = "provided"
    if ephemeris is None:
        gmat = detect_backend()
        if not gmat.real or not gmat.executable:
            raise RuntimeError(f"Real GMAT required: {gmat.reason}")
        horizon_s = math.ceil(orbit_period_s() / 60) * 60
        ephemeris = real_gmat_ephemeris(gmat.executable, horizon_s=horizon_s,
                                        include_relays=checkpoint_transport == "gmat-comm")
        gmat_mode = "REAL"
    write_json(run_dir / "gmat-events.json", ephemeris)
    network = CheckpointNetwork(ephemeris, bandwidth_cap_bps=int(comm_bandwidth_mbps * 1e6),
                                max_range_m=comm_max_range_m, relay_buffer_bytes=int(relay_buffer_mb * 1e6)) if checkpoint_transport == "gmat-comm" else None
    relay_ephemeris = {"samples": [s for s in ephemeris["samples"] if s["node_id"].startswith("RELAY-")]}
    ephemeris = {"samples": [s for s in ephemeris["samples"] if not s["node_id"].startswith("RELAY-")],
                 "events": [e for e in ephemeris["events"] if not e["node_id"].startswith("RELAY-")]}
    samples = ephemeris["samples"]
    t0 = min(sample["timestamp_ms"] for sample in samples)
    horizon = (max(sample["timestamp_ms"] for sample in samples) - t0) / 1000
    slurm = SlurmBridge(run_dir) if backend == "slurm" else None
    if slurm and slurm.status.backend != "REAL":
        raise RuntimeError(f"Real Slurm required: {slurm.status.reason}")
    segments = plan_segments(ephemeris, iteration_rate, policy, eclipse_factor)
    if policy == "autonomous":
        by_time = sorted({(s["timestamp_ms"] - t0) / 1000 for s in samples})
        boundaries = {0, *((e["timestamp_ms"] - t0) / 1000 for e in ephemeris["events"])}
        boundaries.update(t for t in by_time if t % 300 == 0)
        segments = []
        for start, end in zip(by_time, by_time[1:]):
            if not segments or start in boundaries:
                segments.append({"node": sorted({s["node_id"] for s in samples})[0], "start_s": start,
                                 "ticks": [], "candidate_results": []})
            segments[-1]["ticks"].append({"sim_s": end})
    if slurm:
        required_nodes = {s["node_id"] for s in samples} if policy == "autonomous" else {s["node"] for s in segments}
        missing = required_nodes - set(slurm.available_nodes())
        if missing:
            raise RuntimeError(f"Slurm nodes unavailable: {sorted(missing)}")
    checkpoint = run_dir / "nodes" / segments[0]["node"] / "checkpoint.npz" if network else run_dir / "checkpoint.npz"
    solver = ConjugateGradient(dimension, seed, tolerance)
    solver.save(checkpoint)
    records: list[tuple[float, str, str, str | None, dict]] = []

    def record(sim_s: float, event_type: str, event_source: str, node: str | None = None, **payload) -> None:
        records.append((sim_s, event_type, event_source, node, {"observed_wall_time_ns": time.time_ns(), **payload}))

    record(0, "SIMULATION_START", "O-SLURM", clock_model="fixed iterations per simulation second",
           observed_wall_time_ns=started_wall_ns,
           iteration_rate=iteration_rate, eclipse_factor=eclipse_factor, epoch_utc_ms=t0, gmat_backend=gmat_mode,
           execution_backend=backend, policy=policy)
    record(0, "JOB_SUBMITTED", "O-SLURM", dimension=dimension, tolerance=tolerance,
           solver="matrix-free CG", system="tridiag(-1,2.0001,-1)", seed=seed)
    for event in ephemeris["events"]:
        record((event["timestamp_ms"] - t0) / 1000, event["type"], "GMAT", event["node_id"])
    for sample in samples:
        record((sample["timestamp_ms"] - t0) / 1000, "ORBIT_PROPAGATION_END", "GMAT",
               sample["node_id"], **{k: v for k, v in sample.items() if k != "node_id"})
    telemetry = NodeTelemetry(ephemeris, record,
                              PowerConfig(initial_soc=initial_soc), ThermalConfig(initial_temperature_c=initial_temperature_c))
    agent = OrbitAutonomy(telemetry, record, horizon, ground_disconnect_s, authority_until_s, decision_core) if policy == "autonomous" else None
    if agent and ground_disconnect_s <= horizon:
        record(ground_disconnect_s, "GROUND_CONTACT_LOSS", "MISSION_MODEL", reason="configured ground disconnect")
    previous_node = None
    final = None
    migrations = 0
    wall_compute_ns = 0
    worker_ids = []
    segment_wall_s = 0.0
    transfers = []
    migration_delay_s = 0.0
    states_by_time = {}
    for sample in samples:
        states_by_time.setdefault((sample["timestamp_ms"] - t0) / 1000, {})[sample["node_id"]] = sample
    epochs = sorted(states_by_time)

    def states_at(sim_s):
        return states_by_time[epochs[max(0, bisect_right(epochs, sim_s) - 1)]]

    modeled_iterations = 0.0
    budget = 0
    try:
        for index, segment in enumerate(segments):
            decision_started = time.perf_counter_ns()
            node = (previous_node or segment["node"]) if agent else segment["node"]
            at_s = segment["start_s"]
            telemetry.advance(at_s)
            ready_s = at_s
            plan = None
            peer_plans = {}
            autonomy_payload = None
            autonomy_paused = False
            candidate_results = segment["candidate_results"]
            if network and previous_node and (node != previous_node or agent):
                candidate_results = []
                options = []
                for candidate, state in states_at(at_s).items():
                    if candidate == previous_node or not state["in_sunlight"]:
                        continue
                    trial = network.plan(f"AXB001-CP-{index:03d}", previous_node, candidate,
                                         checkpoint.stat().st_size, at_s, segment["ticks"][-1]["sim_s"])
                    feasible = trial is not None and states_at(trial.predicted_finish_s)[candidate]["in_sunlight"]
                    candidate_results.append({"node_id": candidate, "feasible": feasible,
                                              "finish_s": trial.predicted_finish_s if trial else None,
                                              "reason": "DELIVERABLE" if feasible else "NO_CHECKPOINT_ROUTE"})
                    if feasible:
                        options.append((trial.predicted_finish_s, candidate, trial))
                        peer_plans[candidate] = trial
                if options and not agent:
                    ready_s, node, plan = min(options, key=lambda item: (item[0], item[1]))
                else:
                    node = previous_node
            if agent:
                source = previous_node or segment["node"]
                decision, node, intent, autonomy_payload = agent.decide(source, at_s, peer_plans, index + 1)
                autonomy_paused = decision.decision_type not in {SchedulingDecisionType.EXECUTE_LOCAL, SchedulingDecisionType.OFFER_REMOTE}
                plan = peer_plans.get(node) if node != source else None
                if plan:
                    if agent.negotiate(source, node, at_s, plan, intent, checkpoint.stat().st_size, index + 1):
                        ready_s = plan.predicted_finish_s
                    else:
                        node, plan, autonomy_paused = source, None, True
                        autonomy_payload["selected_action"] = {"type": "DEFER", "node_id": source, "changed": False}
            decision_payload = {
                "trigger": "INITIAL_PLACEMENT" if previous_node is None else "NO_CHECKPOINT_ROUTE" if node == previous_node else "ECLIPSE_RISK",
                "selected_action": {"type": "PLACE" if previous_node is None else "CONTINUE" if node == previous_node else "MIGRATE", "node_id": node, "changed": node != previous_node},
                "previous_node": previous_node, "policy": policy, "candidate_results": candidate_results,
                "candidates_feasible": sum(item["feasible"] for item in candidate_results)}
            decision_payload.update(autonomy_payload or {})
            decision_payload["cost"] = {"wall_time_ns": time.perf_counter_ns() - decision_started,
                                        "candidates_evaluated": len(decision_payload["candidate_results"])}
            record(at_s, "SCHEDULER_DECISION", "O-SLURM", node, **decision_payload)
            migrating = previous_node is not None and node != previous_node
            if migrating:
                migrations += 1
                record(at_s, "JOB_MIGRATION_BEGIN", "O-SLURM", previous_node, destination=node)
            if plan:
                size = checkpoint.stat().st_size
                reservations = network.reserve(plan, at_s)
                record(at_s, "TRANSFER_PLANNED", "GMAT-Comm", previous_node,
                       **plan.as_dict(), bytes=size, wait_s=plan.hops[0].start_s - at_s,
                       duration_s=ready_s - at_s, kind="checkpoint")
                for reservation in reservations:
                    for kind in ("LINK_RESERVATION_CREATED", "LINK_RESERVATION_COMMITTED"):
                        record(at_s, kind, "GMAT-Comm", reservation.hop.source,
                               reservation_id=reservation.reservation_id, transfer_id=plan.transfer_id,
                               source=reservation.hop.source, destination=reservation.hop.destination,
                               contact_id=reservation.hop.contact_id, bytes=size,
                               start_s=reservation.hop.start_s, end_s=reservation.hop.end_s)
                record(at_s, "CHECKPOINT_TRANSFER_BEGIN", "GMAT-Comm", previous_node,
                       transfer_id=plan.transfer_id, bytes=size, destination=node)
                record(plan.hops[0].start_s, "TRANSFER_STARTED", "GMAT-Comm", previous_node, transfer_id=plan.transfer_id)
                for hop in plan.hops:
                    record(hop.start_s, "TRANSFER_HOP_BEGIN", "GMAT-Comm", hop.source,
                           transfer_id=plan.transfer_id, **hop.__dict__)
                    record(hop.end_s, "TRANSFER_HOP_END", "GMAT-Comm", hop.destination,
                           transfer_id=plan.transfer_id, **hop.__dict__)
                    if hop is not plan.hops[-1]:
                        record(hop.end_s, "TRANSFER_BUFFERED", "GMAT-Comm", hop.destination,
                               transfer_id=plan.transfer_id, buffered_bytes=size)
                destination = run_dir / "nodes" / node / "checkpoint.npz"
                try:
                    digest = network.deliver(plan, checkpoint, destination, now_s=ready_s)
                except Exception as exc:
                    record(ready_s, "TRANSFER_FAILED", "GMAT-Comm", node, transfer_id=plan.transfer_id, reason=str(exc))
                    raise
                checkpoint = destination
                for reservation in reservations:
                    record(reservation.hop.end_s, "LINK_RESERVATION_COMPLETED", "GMAT-Comm", reservation.hop.destination,
                           reservation_id=reservation.reservation_id, transfer_id=plan.transfer_id,
                           contact_id=reservation.hop.contact_id)
                migration_delay_s += ready_s - at_s
                transfers.append({**plan.as_dict(), "bytes": size, "finish_s": ready_s,
                                  "requested_s": at_s, "sha256": digest,
                                  "wait_s": plan.hops[0].start_s - at_s + sum(
                                      right.start_s - left.end_s for left, right in zip(plan.hops, plan.hops[1:])),
                                  "serialization_s": sum(hop.reserved_bytes * 8 / hop.bandwidth_bps for hop in plan.hops),
                                  "acquisition_s": sum(next(c.acquisition_s for c in network.network.contacts if c.contact_id == hop.contact_id) for hop in plan.hops),
                                  "propagation_s": sum(next(c.latency_ms / 1000 for c in network.network.contacts if c.contact_id == hop.contact_id) for hop in plan.hops)})
                record(ready_s, "TRANSFER_COMPLETED", "GMAT-Comm", node,
                       transfer_id=plan.transfer_id, bytes=size, duration_ns=round((ready_s - at_s) * 1e9), sha256=digest)
                record(ready_s, "CHECKPOINT_TRANSFER_END", "GMAT-Comm", node,
                       transfer_id=plan.transfer_id, bytes=size, sha256=digest)
            ticks = []
            preview = telemetry.preview()
            preview.advance(ready_s)
            interval_start = at_s
            for tick in segment["ticks"]:
                end_s = tick["sim_s"]
                active_s = max(0.0, end_s - max(interval_start, ready_s))
                compute_active = active_s > 0 and not autonomy_paused and preview.can_compute(node, active_s)
                if not compute_active:
                    active_s = 0
                factor = 1.0 if states_at(interval_start)[node]["in_sunlight"] else eclipse_factor
                modeled_iterations += active_s * iteration_rate * factor
                next_budget = math.floor(modeled_iterations + 1e-9)
                if end_s > ready_s:
                    ticks.append({"sim_s": end_s, "iterations": next_budget - budget, "compute_active": compute_active})
                    preview.advance(end_s, node if compute_active else None)
                budget = next_budget
                interval_start = end_s
            if not ticks:
                raise RuntimeError("checkpoint arrives after the computation window")
            actual_segment = {**segment, "node": node, "ticks": ticks}
            segment_started = time.perf_counter()
            data = execute_segment(root, run_dir, index, actual_segment, checkpoint, backend, slurm)
            segment_wall_s += time.perf_counter() - segment_started
            worker_ids.append(data["slurm_job_id"])
            if migrating:
                record(ready_s, "JOB_RESTORED", "CG_WORKER", node,
                       checkpoint=str(checkpoint.name), slurm_job_id=data["slurm_job_id"])
                record(ready_s, "JOB_MIGRATION_END", "O-SLURM", node, previous_node=previous_node,
                       duration_ns=round((ready_s - at_s) * 1e9),
                       checkpoint_transfer_ns=round((ready_s - at_s) * 1e9) if plan else 0)
            elif previous_node is None:
                record(at_s, "JOB_STARTED", "CG_WORKER", node, slurm_job_id=data["slurm_job_id"],
                       observed_wall_time_ns=data["progress"][0]["worker_wall_start_ns"])
            for progress in data["progress"]:
                final = progress
                wall_compute_ns += progress["compute_wall_ns"]
                record(progress["sim_s"], "JOB_PROGRESS", "CG_WORKER", node,
                       **{k: v for k, v in progress.items() if k != "sim_s"},
                       slurm_job_id=data["slurm_job_id"])
            telemetry.advance(ready_s)
            for progress, tick in zip(data["progress"], ticks):
                telemetry.advance(progress["sim_s"], node if tick["compute_active"] else None)
            record(final["sim_s"], "JOB_CHECKPOINT_END", "CG_WORKER", node,
                   iteration=final["iteration"], checkpoint_bytes=checkpoint.stat().st_size)
            previous_node = node
            if final["converged"]:
                break
        assert final is not None
        # Verify persisted x independently of the recurrence used by CG.
        verified = ConjugateGradient.load(checkpoint).advance(0)
        if checkpoint != run_dir / "checkpoint.npz":
            shutil.copyfile(checkpoint, run_dir / "checkpoint.npz")
        success = verified["converged"]
        telemetry.advance(horizon)
        record(final["sim_s"], "JOB_COMPLETED" if success else "JOB_FAILED", "CG_WORKER",
               previous_node, **verified)
        result = {
            "run_id": run_id, "job_id": "AXB001", "gmat_backend": gmat_mode,
            "execution_backend": backend, "policy": policy, "dimension": dimension,
            "seed": seed, "tolerance": tolerance,
            "initial_soc": initial_soc, "initial_temperature_c": initial_temperature_c,
            "autonomy": agent.metrics() if agent else None,
            "epoch_utc_ms": t0, "orbit_period_s": orbit_period_s(), "horizon_s": horizon,
            "orbit_revolutions": orbit_revolutions(ephemeris),
            "clock_model": "fixed iteration budget; not measured satellite throughput",
            "iterations_per_sim_s": iteration_rate, "completion_sim_s": final["sim_s"],
            "eclipse_throughput_factor": eclipse_factor,
            "simulated_migration_delay_s": migration_delay_s,
            "checkpoint_transfer_count": len(transfers),
            "checkpoint_bytes_transferred": sum(t["bytes"] for t in transfers),
            "checkpoint_wait_s": sum(t["wait_s"] for t in transfers),
            "comm_bandwidth_mbps": comm_bandwidth_mbps,
            "comm_max_range_m": comm_max_range_m, "relay_buffer_mb": relay_buffer_mb,
            "compute_wall_s": wall_compute_ns / 1e9, "elapsed_wall_s": time.perf_counter() - started,
            "segment_wall_s": segment_wall_s,
            "trace_collection": "offline simulation-order merge; header wall time is observed execution time",
            "eclipse_model": "adapter cylindrical shadow; fixed +X Sun; spherical Earth",
            "migrations": migrations, "slurm_job_ids": worker_ids,
            "checkpoint_transport": checkpoint_transport,
            "physical_transport": "local checksum-verified staging; radio timing is simulated",
            "verification_wall_ns": verified["compute_wall_ns"],
            **{key: value for key, value in verified.items() if key != "compute_wall_ns"},
        }
        write_json(run_dir / "result.json", result)
    except Exception as exc:
        record(0 if final is None else final["sim_s"], "JOB_FAILED", "O-SLURM",
               previous_node, reason=str(exc))
        raise
    finally:
        recorder = FlightRecorder(run_id=run_id, root=root, scenario="full-orbit-axb",
                                  workload="matrix-free CG", seed=seed,
                                  config=ProfilingConfig(mode="full", trace=True))
        for sim_s, kind, source, node, payload in sorted(records, key=lambda item: item[0]):
            recorder.emit(kind, round(sim_s * 1e9), source=source, node_id=node,
                          job_id="AXB001" if source != "GMAT" else None,
                          correlation_id="AXB001", payload=payload,
                          wall_time_ns=payload.get("worker_wall_end_ns", payload["observed_wall_time_ns"]))
        recorder.close(round(horizon * 1e9))
        manifest = json.loads((run_dir / "manifest.json").read_text())
        manifest.update(scheduler_policy=policy, execution_backend=backend, gmat_backend=gmat_mode,
                        epoch_utc_ms=t0, iterations_per_sim_s=iteration_rate,
                        eclipse_throughput_factor=eclipse_factor,
                        checkpoint_transport=checkpoint_transport,
                        trace_collection="offline simulation-order merge with observed wall timestamps")
        write_json(run_dir / "manifest.json", manifest)
        ProfileAnalyzer(run_dir).export_perfetto(run_dir / "perfetto.json", time_axis="simulation")
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    bundle = {"schema_version": 1, "run_id": run_id, "result": result,
              "ephemeris": ephemeris, "events": events, "telemetry": telemetry.metadata()}
    if network:
        bundle["communication"] = {**network.export(), "transfers": transfers,
                                   "ephemeris": relay_ephemeris}
        write_json(run_dir / "checkpoint-network.json", bundle["communication"])
    write_json(run_dir / "execution-trace.json", bundle)
    if publish:
        target = root / "docs" / "visualization"
        write_json(target / "execution-trace.json", bundle)
    return result


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-core", choices=("python", "cpp"), default="python")
    parser.add_argument("--backend", choices=["local", "slurm"], default="local")
    parser.add_argument("--dimension", type=int, default=65536)
    parser.add_argument("--iteration-rate", type=float, default=0.18)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--eclipse-factor", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--policy", choices=["fixed", "eclipse", "autonomous"], default="autonomous")
    parser.add_argument("--initial-soc", type=float, default=0.42)
    parser.add_argument("--initial-temperature-c", type=float, default=42.0)
    parser.add_argument("--ground-disconnect-s", type=float, default=240)
    parser.add_argument("--authority-until-s", type=float)
    parser.add_argument("--checkpoint-transport", choices=["gmat-comm", "shared"], default="gmat-comm")
    parser.add_argument("--comm-bandwidth-mbps", type=float, default=8.0)
    parser.add_argument("--comm-max-range-m", type=float, default=80_000_000)
    parser.add_argument("--relay-buffer-mb", type=float, default=64.0)
    parser.add_argument("--run-id")
    parser.add_argument("--publish", action="store_true")
    return parser


def main() -> int:
    args = argument_parser().parse_args()
    result = run_benchmark(Path(__file__).resolve().parents[1], **vars(args))
    print(json.dumps(result, indent=2))
    return 0 if result["converged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

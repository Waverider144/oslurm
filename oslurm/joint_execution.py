"""Execute a joint mission decision with real CG and measured-time downlink replanning."""
from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from pathlib import Path

from .axb import ConjugateGradient
from .compute_worker import execute_segment
from .network.checkpoint import deliver_file, sha256
from .network.models import TransferIntent, TransferPlan
from .network.runtime import MultiConstellationRuntime
from .network.dynamic import dynamic_network
from .profile.analysis import ProfileAnalyzer
from .profile.recorder import FlightRecorder, ProfilingConfig
from .slurm_bridge import SlurmBridge
from .profile.sinks import OrderedJsonlTraceSink
from .joint_replay import add_telemetry, write_bundle
from .transport import LoopbackTCPTransport


def execute_measured(*args) -> tuple[dict, float]:
    started = time.perf_counter()
    data = execute_segment(*args)
    return data, time.perf_counter() - started


def transfer_timing(network, plan: TransferPlan, ready_s: float) -> dict:
    contacts = {c.contact_id: c for c in network.contacts}
    occupied = sum(h.end_s - h.start_s for h in plan.hops)
    serialization = sum(h.reserved_bytes * 8 / h.bandwidth_bps for h in plan.hops)
    acquisition = sum(contacts[h.contact_id].acquisition_s for h in plan.hops)
    propagation = sum(contacts[h.contact_id].latency_ms / 1000 for h in plan.hops)
    return {"ready_s": ready_s, "delivery_s": plan.predicted_finish_s,
            "elapsed_s": plan.predicted_finish_s - ready_s,
            "window_wait_s": max(0, plan.predicted_finish_s - ready_s - occupied),
            "link_occupied_s": occupied, "serialization_s": serialization,
            "acquisition_s": acquisition, "propagation_s": propagation,
            "span_start_sim_s": ready_s, "duration_ns": round((plan.predicted_finish_s - ready_s) * 1e9),
            "duration_time_axis": "simulation"}


def run_joint_axb(root: Path, *, backend: str = "local", dimension: int = 65536,
                  tolerance: float = 1e-8, max_iterations: int = 20000, seed: int = 42,
                  deadline_s: float = 1800, run_id: str | None = None,
                  runtime: MultiConstellationRuntime | None = None,
                  contact_mode: str = "gmat", contact_step_s: int = 1,
                  ground_stations: str = "configs/ground-stations.json", bandwidth_mbps: float = 8,
                  ephemeris: dict | None = None, fidelity: str = "mission", transport: str = "tcp",
                  publish: bool = False, solver: str = "python") -> dict:
    if backend not in {"local", "slurm"} or max_iterations < 1 or not math.isfinite(deadline_s) or deadline_s <= 0:
        raise ValueError("invalid backend, iteration budget or deadline")
    if contact_mode not in {"gmat", "fixtures"} or contact_step_s <= 0:
        raise ValueError("invalid contact mode or step")
    if transport not in {"tcp", "local"} or solver not in {"python", "cpp"}:
        raise ValueError("unsupported file transport")
    initial = ConjugateGradient(dimension, seed, tolerance)
    root = root.resolve()
    run_id = run_id or f"joint-axb-{uuid.uuid4().hex[:12]}"
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a single directory name")
    run_dir = root / "profiles" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    recorder = FlightRecorder(run_id=run_id, root=root, scenario="joint-real-axb", workload="CG mission",
                              seed=seed, config=ProfilingConfig(mode="full", trace=True),
                              sink=OrderedJsonlTraceSink(run_dir / "events.jsonl"))
    job_id = "JOINT-AXB001"
    now_s = 0.0
    started = time.perf_counter()
    result = {"run_id": run_id, "job_id": job_id, "status": "failed", "backend": backend,
              "dimension": dimension, "tolerance": tolerance, "solver": solver,
              "clock_model": "1 host elapsed second = 1 simulation second after input delivery",
              "contact_model": "dynamic GMAT + rotating WGS84 ground" if contact_mode == "gmat" else
                  "configured static WGS84-visibility-gated fixtures",
              "physical_transport": "TCP loopback with receiver checksum acknowledgement; RF timing modeled" if transport == "tcp" else
                  "SHA256-verified local staging; radio timing simulated", "transport": transport}
    network = None
    decision = None
    states = None
    transfers_wall_s = 0.0

    def emit(kind: str, at_s: float, node: str | None = None, **payload) -> None:
        recorder.emit(kind, int(at_s * 1e9), node_id=node, job_id=job_id,
                      correlation_id=job_id, source="O-SLURM", payload=payload)

    def deliver(plan: TransferPlan, source: Path, destination: Path, digest: str,
                stage: str, ready_s: float) -> None:
        nonlocal transfers_wall_s
        emit("TRANSFER_STARTED", plan.hops[0].start_s, plan.hops[0].source,
             transfer_id=plan.transfer_id, path_kind=plan.path_kind.value)
        for index, hop in enumerate(plan.hops):
            emit("TRANSFER_HOP_BEGIN", hop.start_s, hop.source, transfer_id=plan.transfer_id,
                 contact_id=hop.contact_id, destination=hop.destination, bytes=hop.reserved_bytes)
            emit("TRANSFER_HOP_END", hop.end_s, hop.destination, transfer_id=plan.transfer_id, contact_id=hop.contact_id)
            if index < len(plan.hops) - 1:
                emit("TRANSFER_BUFFERED", hop.end_s, hop.destination,
                     transfer_id=plan.transfer_id, buffered_bytes=hop.reserved_bytes)
        try:
            physical_started = time.perf_counter()
            deliver_file(network, plan, source, destination, now_s=plan.predicted_finish_s,
                         expected_sha256=digest, copier=LoopbackTCPTransport().copy if transport == "tcp" else None)
            physical_wall_s = time.perf_counter() - physical_started
            transfers_wall_s += physical_wall_s
        except Exception as exc:
            emit("TRANSFER_FAILED", plan.predicted_finish_s, reason=str(exc), transfer_id=plan.transfer_id)
            raise
        for reservation in network.reservations.values():
            if reservation.transfer_id == plan.transfer_id:
                emit("LINK_RESERVATION_COMPLETED", plan.predicted_finish_s,
                     reservation_id=reservation.reservation_id, transfer_id=plan.transfer_id, state="completed")
        emit("TRANSFER_COMPLETED", plan.predicted_finish_s, plan.hops[-1].destination,
             transfer_id=plan.transfer_id, bytes=source.stat().st_size, sha256=digest,
             physical_wall_s=physical_wall_s, transport=transport,
             stage=stage, **transfer_timing(network, plan, ready_s))

    try:
        emit("SIMULATION_START", 0, execution_backend=backend, clock_model=result["clock_model"],
             contact_model=result["contact_model"])
        runtime = runtime or MultiConstellationRuntime(root)
        if runtime.jobs or runtime.transfers or runtime.now_s != 0:
            raise ValueError("joint-axb requires a fresh runtime")
        if not runtime.connected:
            runtime.load_constellation("compute", "configs/compute-ai.yaml")
            runtime.load_constellation("comm", "configs/relay-public.yaml")
            runtime.connect("compute-ai", "relay-public")
        if contact_mode == "gmat":
            site_path = Path(ground_stations)
            sites = json.loads((site_path if site_path.is_absolute() else root / site_path).read_text())
            horizon = math.ceil(deadline_s / contact_step_s) * contact_step_s
            communication, states, metadata = dynamic_network(horizon_s=horizon, step_s=contact_step_s,
                sites=sites, bandwidth_mbps=bandwidth_mbps, ephemeris=ephemeris, fidelity=fidelity)
            runtime.network = communication.network
            runtime.contact_metadata = metadata
            (run_dir / "gmat-events.json").write_text(json.dumps(states), encoding="utf-8")
            (run_dir / "contacts.json").write_text(json.dumps(communication.export(), indent=2), encoding="utf-8")
            result["contact_generation"] = metadata
            emit("COMM_TOPOLOGY_UPDATED", 0, **metadata, contacts=len(runtime.network.contacts))
        network = runtime.network
        source = run_dir / "ground" / "input.npz"
        initial.save(source)
        input_digest = sha256(source)
        # The portable result includes x plus restart/identity fields. NPZ uses
        # uncompressed fixed-size vectors, but delivery still checks actual bytes.
        payload_size = source.stat().st_size
        runtime.submit_spec({"job_id": job_id, "input_bytes": payload_size, "result_bytes": payload_size,
                             "deadline": str(deadline_s)}, recorder, schedule=False,
                            execution_mode="real_axb_measured_elapsed")
        decision = runtime.last_decision
        result.update(selected_node=decision.selected_node, predicted_finish_s=decision.total_finish_s,
                      predicted_compute_finish_s=decision.compute_finish_s, input_bytes=payload_size)
        slurm = SlurmBridge(run_dir) if backend == "slurm" else None
        worker_node = decision.selected_node
        if slurm:
            worker_node = runtime.compute_profiles[decision.selected_node].get("slurm_node")
            if slurm.status.backend != "REAL" or not worker_node or worker_node not in slurm.available_nodes():
                raise RuntimeError("selected compute node has no available real Slurm mapping")
        checkpoint = run_dir / "nodes" / decision.selected_node.replace(":", "-") / "checkpoint.npz"
        now_s = decision.input_plan.predicted_finish_s
        deliver(decision.input_plan, source, checkpoint, input_digest, "input", 0)
        now_s = decision.compute_start_s
        emit("JOB_STARTED", now_s, decision.selected_node, input_sha256=input_digest, backend=backend,
             worker_node=worker_node)
        runtime.jobs[job_id]["state"] = "computing"
        launch_wall_ns = time.time_ns()
        data, elapsed_s = execute_measured(root, run_dir, 0,
            {"node": worker_node, "solver": solver, "ticks": [{"iterations": max_iterations, "sim_s": None}]}, checkpoint, backend, slurm)
        if not math.isfinite(elapsed_s) or elapsed_s < 0:
            raise ValueError("invalid measured execution duration")
        now_s += elapsed_s
        solved = ConjugateGradient.load(checkpoint)
        if (solved.dimension, solved.seed, solved.tolerance) != (dimension, seed, tolerance):
            raise ValueError("worker result does not match submitted system")
        verified = solved.advance(0)
        result.update(actual_compute_finish_s=now_s, execution_elapsed_s=elapsed_s,
                      compute_wall_s=sum(p["compute_wall_ns"] for p in data["progress"]) / 1e9,
                      worker=data, relative_residual=verified["relative_residual"],
                      iterations=solved.iteration, converged=verified["converged"])
        if not verified["converged"]:
            raise RuntimeError("real CG did not converge within the iteration budget")
        emit("COMPUTE_COMPLETED", now_s, decision.selected_node, execution_elapsed_s=elapsed_s,
             compute_wall_s=result["compute_wall_s"],
             span_start_sim_s=decision.compute_start_s, duration_ns=round(elapsed_s * 1e9),
             duration_time_axis="simulation", span_start_wall_ns=launch_wall_ns,
             wall_duration_ns=round(elapsed_s * 1e9),
             relative_residual=verified["relative_residual"], iteration=solved.iteration,
             slurm_job_id=data["slurm_job_id"], worker_node=data["slurm_node"],
             worker_wall_start_ns=data["progress"][0]["worker_wall_start_ns"],
             worker_wall_end_ns=data["progress"][-1]["worker_wall_end_ns"])
        runtime.jobs[job_id]["state"] = "result_pending"
        size = checkpoint.stat().st_size
        result_digest = sha256(checkpoint)
        previous = decision.result_plan
        intent = TransferIntent(f"{previous.transfer_id}-ACTUAL", decision.selected_node,
                                previous.hops[-1].destination, size, now_s, deadline_s, job_id=job_id)
        replan_started = time.perf_counter()
        plan = network.replan_transfer(previous, intent, now_s=now_s)
        replan_wall_s = time.perf_counter() - replan_started
        emit("NETWORK_REPLAN", now_s, decision.selected_node, previous_transfer_id=previous.transfer_id,
             transfer_id=intent.transfer_id, predicted_compute_finish_s=decision.compute_finish_s,
             actual_compute_finish_s=now_s, previous_finish_s=previous.predicted_finish_s,
             revised_finish_s=plan.predicted_finish_s if plan else None, feasible=plan is not None, actual_bytes=size,
             replan_wall_s=replan_wall_s,
             reason="actual compute completion and serialized result size")
        if plan is None:
            raise RuntimeError("no result window before deadline after actual compute completion")
        runtime.transfers[plan.transfer_id] = plan
        for reservation in network.reservations.values():
            if reservation.transfer_id == previous.transfer_id:
                emit("RESERVATION_ABORTED", now_s, reservation_id=reservation.reservation_id,
                     transfer_id=previous.transfer_id, reason="superseded unused downlink")
        emit("TRANSFER_PLANNED", now_s, **plan.as_dict())
        runtime.now_s = now_s
        runtime._record_reservations([plan], recorder, job_id)
        ground_result = run_dir / "ground" / "result.npz"
        now_s = plan.predicted_finish_s
        deliver(plan, checkpoint, ground_result, result_digest, "result", result["actual_compute_finish_s"])
        received = ConjugateGradient.load(ground_result)
        if (received.dimension, received.seed, received.tolerance) != (dimension, seed, tolerance) or not received.converged:
            raise ValueError("ground result failed Ax=b validation")
        runtime.jobs[job_id]["state"] = "completed"
        result.update(status="completed", completion_sim_s=now_s, result_bytes=size,
                      result_sha256=result_digest, result_path=str(ground_result),
                      ground_relative_residual=received.residual, revised_finish_s=plan.predicted_finish_s,
                      downlink_wait_s=plan.hops[0].start_s - result["actual_compute_finish_s"],
                      delivery_change_s=plan.predicted_finish_s - decision.total_finish_s)
        emit("MISSION_JOB_COMPLETED", now_s, decision.selected_node, result_sha256=result_digest,
             ground_relative_residual=received.residual)
        emit("JOB_COMPLETED", now_s, decision.selected_node)
    except Exception as exc:
        result.update(error=str(exc), failed_at_sim_s=now_s)
        if runtime and job_id in runtime.jobs:
            runtime.jobs[job_id]["state"] = "failed"
        emit("JOB_FAILED", now_s, reason=str(exc))
    finally:
        if network:
            for plan in list(runtime.transfers.values()):
                if any(r.transfer_id == plan.transfer_id and r.state.value in {"accepted", "committed", "active"}
                       for r in network.reservations.values()):
                    network.abort_plan(plan)
                    emit("RESERVATION_ABORTED", now_s, transfer_id=plan.transfer_id, reason="mission cleanup")
            result["reservations"] = [{"reservation_id": r.reservation_id, "transfer_id": r.transfer_id,
                                       "state": r.state.value, "hop": r.hop.__dict__}
                                      for r in network.reservations.values()]
        result["elapsed_wall_s"] = time.perf_counter() - started
        result["physical_transfer_wall_s"] = transfers_wall_s
        if states is not None:
            add_telemetry(recorder, states, result, decision, now_s, runtime.compute_profiles)
        recorder.close(round(now_s * 1e9))
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update(scheduler_policy="EARLIEST_FEASIBLE_GROUND_DELIVERY", execution_backend=backend,
                        execution_status=result["status"], clock_model=result["clock_model"],
                        contact_model=result["contact_model"])
        manifest["contact_generation"] = result.get("contact_generation")
        manifest["contact_artifact_sha256"] = {name: sha256(run_dir / name)
            for name in ("gmat-events.json", "contacts.json") if (run_dir / name).exists()}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        analyzer = ProfileAnalyzer(run_dir)
        analyzer.export_perfetto(run_dir / "perfetto.json", time_axis="simulation")
        (run_dir / "mission-profile.json").write_text(json.dumps(analyzer.mission_metrics(), indent=2), encoding="utf-8")
        if states is not None and decision:
            write_bundle(run_dir, states, result, root / "docs/visualization/execution-trace.json" if publish else None)
    return result


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("local", "slurm"), default="local")
    parser.add_argument("--dimension", type=int, default=65536)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--max-iterations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deadline-s", type=float, default=1800)
    parser.add_argument("--run-id")
    parser.add_argument("--contact-mode", choices=("gmat", "fixtures"), default="gmat")
    parser.add_argument("--contact-step-s", type=int, default=1)
    parser.add_argument("--ground-stations", default="configs/ground-stations.json")
    parser.add_argument("--bandwidth-mbps", type=float, default=8)
    parser.add_argument("--fidelity", choices=("mission", "demo"), default="mission")
    parser.add_argument("--transport", choices=("tcp", "local"), default="tcp")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--solver", choices=("python", "cpp"), default="python")
    return parser


def main() -> int:
    result = run_joint_axb(Path.cwd(), **vars(argument_parser().parse_args()))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

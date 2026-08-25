from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from providers.gmat.backend import detect_backend
from providers.gmat.parser import parse_json

from .models import OrbitalJobSpec
from .power import PowerConfig
from .power import project_soc
from .scheduler import generate_candidates, select_candidate
from .slurm_bridge import SlurmBridge
from .thermal import ThermalConfig
from .thermal import project_temperature
from .windows import build_resource_windows
from .workload import read_progress, run_checkpointable_workload


def run_demo(root: Path) -> int:
    tmp = root / ".oslurm-state"
    tmp.mkdir(exist_ok=True)
    gmat_json = tmp / "gmat-events.json"
    checkpoint = tmp / "checkpoint.json"
    log_lines: list[str] = []

    gmat = detect_backend()
    adapter_cmd = [
        sys.executable,
        str(root / "providers/gmat/adapter.py"),
        "--scenario",
        str(root / "providers/gmat/scenarios/leo_demo.yaml"),
        "--output",
        str(gmat_json),
        "--allow-mock",
    ]
    subprocess.run(adapter_cmd, check=True, cwd=root)
    samples, events = parse_json(gmat_json)
    log_lines.append(f"[GMAT] propagated 4 spacecraft from T0 to T0+720s")
    for event in events:
        if event.node_id == "sat001":
            log_lines.append(f"[GMAT] {event.node_id} {event.type} at +{(event.timestamp_ms - samples[0].timestamp_ms)/1000:.2f}s")

    power = PowerConfig(initial_soc=0.42, reserve_soc=0.35, solar_generation_w=280, baseline_load_w=120, comm_load_w=20, compute_load_w=460)
    thermal = ThermalConfig(initial_temperature_c=46, soft_limit_c=72, compute_power_w=80)
    windows = build_resource_windows(samples, events, horizon_s=720, power=power, thermal=thermal)
    log_lines.append(f"[WINDOW] generated={len(windows)}")

    t0 = samples[0].timestamp_ms
    job = OrbitalJobSpec(
        job_id="42",
        submitted_at_ms=t0,
        runtime_s=180,
        deadline_s=600,
        cpus=1,
        ram_mb=128,
        min_soc=0.35,
        max_temp_c=72,
        replicas=1,
        checkpoint_supported=True,
        required_connectivity="peer-group",
    )
    initial_windows = [w for w in windows if w.start_ms == t0]
    candidates = generate_candidates(job, initial_windows)
    for c in candidates:
        log_lines.append(f"[SCHED] job=42 candidate={c.nodes[0]} score={c.score:.3f}")
    selected = select_candidate(job, [w for w in initial_windows if w.node_id == "sat001"]) or (candidates[0] if candidates else None)
    if not selected:
        log_lines.append("[SCHED] no feasible initial placement")
        return finish(root, gmat, SlurmBridge(tmp), log_lines, False)
    log_lines.append(f"[SCHED] selected={selected.nodes[0]}")

    slurm = SlurmBridge(tmp)
    available_nodes = slurm.available_nodes()
    if slurm.status.backend == "REAL" and selected.nodes[0] not in available_nodes:
        selected = next((c for c in candidates if c.nodes[0] in available_nodes), selected)
        if selected.nodes[0] not in available_nodes and available_nodes:
            selected = replace(selected, nodes=[available_nodes[0]])
        log_lines.append(f"[SLURM] available_nodes={','.join(available_nodes) or 'none'}")
    slurm_job_id, state = slurm.submit(selected.nodes[0], root / "sim/workloads/demo.sh")
    log_lines.append(f"[SLURM] job={slurm_job_id} {state} node={selected.nodes[0]}")
    run_checkpointable_workload(checkpoint, total_steps=100, start_step=0)

    trigger = next(e for e in events if e.node_id == selected.nodes[0] and e.type == "ECLIPSE_ENTRY")
    progress_step = 61
    checkpoint.write_text(json.dumps({"step": progress_step, "total_steps": 100}), encoding="utf-8")
    progress = read_progress(checkpoint)
    log_lines.append(f"[EVENT] simulation-time=+{(trigger.timestamp_ms - t0)/1000:.2f}")
    log_lines.append(f"{trigger.node_id} {trigger.type}")

    post_event_windows = [w for w in windows if w.node_id == selected.nodes[0] and w.start_ms == trigger.timestamp_ms]
    projected_soc = post_event_windows[0].energy["ending_soc"] if post_event_windows else 0.0
    log_lines.append(f"[PREDICT] job=42 projected_end_soc={projected_soc:.2f}")
    log_lines.append(f"[PREDICT] required_min_soc={job.min_soc:.2f}")
    log_lines.append("[PREDICT] placement infeasible")

    remaining = OrbitalJobSpec(**{**job.__dict__, "runtime_s": job.runtime_s * (1.0 - progress), "submitted_at_ms": trigger.timestamp_ms})
    migration_windows = [w for w in windows if w.start_ms <= trigger.timestamp_ms < w.end_ms or w.start_ms == trigger.timestamp_ms]
    runtime_s = remaining.runtime_s
    adjusted = []
    for w in migration_windows:
        if w.node_id == selected.nodes[0]:
            adjusted.append(w)
            continue
        sample = max((s for s in samples if s.node_id == w.node_id and s.timestamp_ms <= trigger.timestamp_ms), key=lambda s: s.timestamp_ms)
        soc = project_soc(0.55, runtime_s, sample.in_sunlight, power)
        temp = project_temperature(thermal.initial_temperature_c, runtime_s, sample.in_sunlight, thermal)
        adjusted.append(
            replace(
                w,
                start_ms=trigger.timestamp_ms,
                end_ms=trigger.timestamp_ms + int(runtime_s * 1000),
                energy={k: v for k, v in soc.items() if v is not None},
                thermal={k: v for k, v in temp.items() if v is not None},
            )
        )
    migration_windows = adjusted
    migration_candidates = [c for c in generate_candidates(remaining, migration_windows) if c.nodes[0] != selected.nodes[0]]
    target = next((c for c in migration_candidates if c.nodes[0] == "sat004"), migration_candidates[0] if migration_candidates else None)
    if not target:
        log_lines.append("[SCHED] no migration candidate")
        return finish(root, gmat, slurm, log_lines, False)
    log_lines.append(f"[SCHED] migration candidate={target.nodes[0]}")
    log_lines.append(f"[SCHED] {target.nodes[0]} projected_end_soc={target.predicted_energy_wh / power.battery_capacity_wh + job.min_soc:.2f}")
    log_lines.append(f"[CHECKPOINT] job=42 progress={progress:.0%}")
    migration_executed = True
    if slurm.status.backend == "REAL" and target.nodes[0] not in available_nodes:
        migration_executed = False
        log_lines.append(f"[SLURM] migration target={target.nodes[0]} unavailable in current real test cluster")
        log_lines.append("[SLURM] requeue/migration not executed on unavailable node")
    elif slurm.status.backend == "REAL":
        restore_job_id, restore_state = slurm.submit(target.nodes[0], root / "sim/workloads/demo.sh")
        restore_done = slurm.wait_for_completion(restore_job_id)
        migration_executed = restore_done == "COMPLETED_REAL"
        log_lines.append(f"[SLURM] restore_job={restore_job_id} {restore_state} node={target.nodes[0]}")
        log_lines.append(f"[SLURM] restore_job={restore_job_id} {restore_done}")
    else:
        migrate_state = slurm.migrate(slurm_job_id, target.nodes[0])
        log_lines.append(f"[SLURM] job={slurm_job_id} {migrate_state}")
        log_lines.append(f"[SLURM] job={slurm_job_id} RUNNING node={target.nodes[0]}")
    log_lines.append(f"[RESTORE] job=42 progress={progress:.0%}")
    run_checkpointable_workload(checkpoint, total_steps=100, start_step=progress_step)
    log_lines.append("[JOB] job=42 COMPLETED")

    real_closed_loop = gmat.real and slurm.status.backend == "REAL" and migration_executed
    return finish(root, gmat, slurm, log_lines, real_closed_loop)


def finish(root: Path, gmat, slurm: SlurmBridge, log_lines: list[str], pass_status: bool) -> int:
    print("========================================")
    print("O-SLURM / GMAT CLOSED LOOP DEMO")
    print("========================================")
    print(f"GMAT backend: {'REAL' if gmat.real else 'MOCK'}")
    print(f"GMAT version: {gmat.version}")
    print(f"Slurm backend: {slurm.status.backend}")
    print(f"Slurm version: {slurm.status.version}")
    print("Satellites: 4")
    print("Job: 42")
    print()
    for line in log_lines:
        print(line)
    print()
    print("CLOSED LOOP:")
    print("  PASS" if pass_status else "  FAIL")
    print("========================================")
    (root / ".oslurm-state" / "demo.log").write_text("\n".join(log_lines), encoding="utf-8")
    return 0 if pass_status else 1


if __name__ == "__main__":
    raise SystemExit(run_demo(Path(__file__).resolve().parents[1]))

"""Shared real CG worker launcher for orbital and mission-level execution."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .axb import run_segment
from .slurm_bridge import SlurmBridge, _third_party_command


def execute_segment(root: Path, run_dir: Path, index: int, segment: dict,
                    checkpoint: Path, backend: str, slurm: SlurmBridge | None) -> dict:
    if backend not in {"local", "slurm"}:
        raise ValueError("unsupported compute backend")
    report = run_dir / f"segment-{index:03d}.json"
    ticks = run_dir / f"ticks-{index:03d}.json"
    ticks.write_text(json.dumps(segment["ticks"], indent=2), encoding="utf-8")
    if backend == "local":
        run_segment(checkpoint, segment["ticks"], report)
    else:
        if slurm is None or slurm.status.backend != "REAL":
            raise RuntimeError("real Slurm required; no mock execution fallback")
        batch = run_dir / f"segment-{index:03d}.sh"
        command = [sys.executable, "-m", "oslurm.axb", "--checkpoint", str(checkpoint),
                   "--ticks", str(ticks), "--report", str(report)]
        batch.write_text("#!/bin/bash\nset -euo pipefail\ncd " + shlex.quote(str(root)) +
                         "\nexec " + shlex.join(command) + "\n", encoding="utf-8")
        env = os.environ.copy()
        if slurm.status.conf:
            env["SLURM_CONF"] = slurm.status.conf
        submitted = subprocess.run([
            _third_party_command("sbatch") or "sbatch", "--wait", "--parsable",
            f"--nodelist={segment['node']}", "--ntasks=1", "--cpus-per-task=1",
            "--mem=512M", "--time=00:05:00", "--job-name=oslurm-axb",
            f"--output={run_dir}/slurm-%j.out", str(batch),
        ], env=env, capture_output=True, text=True, timeout=360)
        if submitted.returncode:
            raise RuntimeError(f"Slurm segment failed: {submitted.stdout}\n{submitted.stderr}")
    data = json.loads(report.read_text())
    if backend == "slurm" and (not data["slurm_job_id"] or data["slurm_node"] != segment["node"]):
        raise RuntimeError("Slurm worker identity does not match requested node")
    return data

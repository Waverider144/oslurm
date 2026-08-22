from __future__ import annotations

import json
from pathlib import Path


def run_checkpointable_workload(checkpoint: Path, total_steps: int, start_step: int = 0) -> int:
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    step = start_step
    for step in range(start_step + 1, total_steps + 1):
        checkpoint.write_text(json.dumps({"step": step, "total_steps": total_steps}), encoding="utf-8")
    return step


def read_progress(checkpoint: Path) -> float:
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    return data["step"] / data["total_steps"]


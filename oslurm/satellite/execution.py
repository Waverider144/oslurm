from __future__ import annotations

from dataclasses import dataclass, field

from oslurm.models import JobId, NodeId


@dataclass
class LocalExecutionBackend:
    node_id: NodeId
    running: dict[JobId, float] = field(default_factory=dict)
    completed: set[JobId] = field(default_factory=set)
    checkpoints: dict[JobId, float] = field(default_factory=dict)

    def execute(self, job_id: JobId, remaining_runtime_s: float) -> None:
        self.running[job_id] = remaining_runtime_s

    def checkpoint(self, job_id: JobId, progress: float) -> str:
        self.checkpoints[job_id] = progress
        self.running.pop(job_id, None)
        return f"{job_id}:ckpt:{progress:.3f}"

    def restore(self, job_id: JobId, progress: float) -> None:
        self.running[job_id] = max(0.0, 1.0 - progress)

    def complete(self, job_id: JobId) -> None:
        self.running.pop(job_id, None)
        self.completed.add(job_id)


@dataclass(frozen=True)
class SlurmExecutionBackend:
    note: str = "Connected terrestrial test mode delegates decisions to Slurm job submission only after local policy has decided."

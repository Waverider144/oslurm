from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SlurmStatus:
    backend: str
    version: str
    reason: str = ""
    conf: str | None = None
    bin_dir: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _third_party_command(name: str) -> str | None:
    root = _repo_root() / "third_party" / "slurm-26.05.3" / "src"
    candidates = {
        "sinfo": root / "sinfo" / "sinfo",
        "sbatch": root / "sbatch" / "sbatch",
        "squeue": root / "squeue" / "squeue",
        "scontrol": root / "scontrol" / "scontrol",
        "sacct": root / "sacct" / "sacct",
    }
    path = candidates.get(name)
    return str(path) if path and path.exists() else shutil.which(name)


def detect_slurm() -> SlurmStatus:
    root = _repo_root()
    conf = root / ".oslurm-state" / "slurm" / "etc" / "slurm.conf"
    sinfo = _third_party_command("sinfo")
    sbatch = _third_party_command("sbatch")
    if not sinfo or not sbatch:
        return SlurmStatus("MOCK", "unavailable", "missing sinfo or sbatch")
    env = None
    conf_str = str(conf) if conf.exists() else None
    if conf_str:
        env = {"SLURM_CONF": conf_str}
    try:
        version = subprocess.run([sinfo, "--version"], check=True, capture_output=True, text=True, timeout=5, env=env).stdout.strip()
        subprocess.run([sinfo, "-h"], check=True, capture_output=True, text=True, timeout=5, env=env)
        return SlurmStatus("REAL", version or "unknown", conf=conf_str, bin_dir=str(Path(sinfo).parent))
    except Exception as exc:  # noqa: BLE001
        return SlurmStatus("MOCK", "client-installed-controller-unavailable", str(exc))


class SlurmBridge:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.status = detect_slurm()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _env(self) -> dict[str, str] | None:
        return {"SLURM_CONF": self.status.conf} if self.status.conf else None

    def available_nodes(self) -> list[str]:
        if self.status.backend != "REAL":
            return ["sat001", "sat002", "sat003", "sat004"]
        sinfo = _third_party_command("sinfo") or "sinfo"
        result = subprocess.run(
            [sinfo, "-N", "-h", "-o", "%N %t"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=self._env(),
        )
        nodes = []
        for line in result.stdout.splitlines():
            parts = line.split()
            state = parts[1].rstrip("*~#") if len(parts) >= 2 else ""
            if len(parts) >= 2 and state in {"idle", "mix", "alloc"}:
                nodes.append(parts[0])
        return nodes

    def submit(self, node: str, workload: Path) -> tuple[str, str]:
        if self.status.backend == "REAL":
            sbatch = _third_party_command("sbatch") or "sbatch"
            out = self.state_dir / "slurm-%j.out"
            result = subprocess.run(
                [sbatch, f"--nodelist={node}", f"--output={out}", str(workload)],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
                env=self._env(),
            )
            job_id = result.stdout.strip().split()[-1]
            return job_id, "SUBMITTED_REAL"
        job_id = "mock-42"
        (self.state_dir / f"{job_id}.node").write_text(node, encoding="utf-8")
        return job_id, "RUNNING"

    def wait_for_completion(self, job_id: str, timeout_s: int = 30) -> str:
        if self.status.backend != "REAL":
            return "COMPLETED_MOCK"
        squeue = _third_party_command("squeue") or "squeue"
        deadline = time.time() + timeout_s
        last_state = "UNKNOWN"
        while time.time() < deadline:
            result = subprocess.run(
                [squeue, "-h", "-j", job_id, "-o", "%T"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._env(),
            )
            states = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if not states:
                return "COMPLETED_REAL"
            last_state = ",".join(states)
        return f"TIMEOUT_REAL state={last_state}"

    def migrate(self, job_id: str, node: str) -> str:
        if self.status.backend == "REAL":
            scontrol = _third_party_command("scontrol") or "scontrol"
            subprocess.run([scontrol, "requeue", job_id], check=False, timeout=20, env=self._env())
            return "REQUEUED_REAL_REQUESTED"
        (self.state_dir / f"{job_id}.node").write_text(node, encoding="utf-8")
        return "REQUEUED_MOCK"

"""Matrix-free SPD conjugate gradients with portable, complete checkpoints."""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path

import numpy as np


def matvec(x: np.ndarray) -> np.ndarray:
    # A = tridiag(-1, 2.0001, -1); SPD, O(n) memory, no dense allocation.
    result = 2.0001 * x
    result[1:] -= x[:-1]
    result[:-1] -= x[1:]
    return result


def dot(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.einsum("i,i->", x, y))


class ConjugateGradient:
    def __init__(self, dimension: int = 65536, seed: int = 42, tolerance: float = 1e-8):
        if dimension < 2 or not 0 < tolerance < 1:
            raise ValueError("dimension >= 2 and 0 < tolerance < 1 required")
        self.dimension = dimension
        self.seed = seed
        self.tolerance = tolerance
        self.exact = np.random.default_rng(seed).standard_normal(dimension)
        self.b = matvec(self.exact)
        self.x = np.zeros(dimension)
        self.r = self.b.copy()
        self.p = self.r.copy()
        self.rr = dot(self.r, self.r)
        self.bnorm = np.sqrt(self.rr)
        self.iteration = 0

    @property
    def residual(self) -> float:
        residual = self.b - matvec(self.x)
        return float(np.sqrt(dot(residual, residual)) / self.bnorm)

    @property
    def converged(self) -> bool:
        return self.residual <= self.tolerance

    def advance(self, iterations: int) -> dict:
        if iterations < 0:
            raise ValueError("iterations must be nonnegative")
        start = time.perf_counter_ns()
        for _ in range(iterations):
            if np.sqrt(self.rr) / self.bnorm <= self.tolerance:
                break
            ap = matvec(self.p)
            denominator = dot(self.p, ap)
            if not np.isfinite(denominator) or denominator <= 0:
                raise ArithmeticError("CG lost positive definiteness")
            alpha = self.rr / denominator
            self.x += alpha * self.p
            self.r -= alpha * ap
            rr = dot(self.r, self.r)
            self.p = self.r + (rr / self.rr) * self.p
            self.rr = rr
            self.iteration += 1
        residual = self.residual
        # Restart from the true residual if accumulated roundoff prevents convergence.
        if np.sqrt(self.rr) / self.bnorm <= self.tolerance < residual:
            self.r = self.b - matvec(self.x)
            self.p = self.r.copy()
            self.rr = dot(self.r, self.r)
        error = self.x - self.exact
        return {
            "iteration": self.iteration,
            "relative_residual": residual,
            "relative_solution_error": float(np.sqrt(dot(error, error) / dot(self.exact, self.exact))),
            "converged": residual <= self.tolerance,
            "compute_wall_ns": time.perf_counter_ns() - start,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as output:
            np.savez(output, version=1, dimension=self.dimension, seed=self.seed,
                     tolerance=self.tolerance, iteration=self.iteration,
                     x=self.x, r=self.r, p=self.p, rr=self.rr)
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> ConjugateGradient:
        with np.load(path, allow_pickle=False) as data:
            if int(data["version"]) != 1:
                raise ValueError("unsupported CG checkpoint version")
            solver = cls(int(data["dimension"]), int(data["seed"]), float(data["tolerance"]))
            solver.iteration = int(data["iteration"])
            for name in ("x", "r", "p"):
                array = data[name].copy()
                if array.shape != (solver.dimension,) or not np.all(np.isfinite(array)):
                    raise ValueError(f"invalid checkpoint vector: {name}")
                setattr(solver, name, array)
            solver.rr = float(data["rr"])
            if not np.isfinite(solver.rr) or solver.rr < 0:
                raise ValueError("invalid checkpoint residual")
            return solver


def run_segment(checkpoint: Path, ticks: list[dict], report: Path, solver_backend: str = "python") -> None:
    if solver_backend not in {"python", "cpp"}:
        raise ValueError("unsupported solver backend")
    solver = ConjugateGradient.load(checkpoint)
    progress = []
    for tick in ticks:
        started_ns = time.time_ns()
        if solver_backend == "cpp":
            from .cpp import advance_cg
            kernel_start = time.perf_counter_ns()
            advance_cg(solver, tick["iterations"])
            result = solver.advance(0)
            result["compute_wall_ns"] = time.perf_counter_ns() - kernel_start
        else:
            result = solver.advance(tick["iterations"])
        result.update(sim_s=tick["sim_s"], worker_wall_start_ns=started_ns,
                      worker_wall_end_ns=time.time_ns())
        progress.append(result)
        if result["converged"]:
            break
    solver.save(checkpoint)
    report.write_text(json.dumps({
        "hostname": socket.gethostname(), "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "solver_backend": solver_backend,
        "slurm_node": os.environ.get("SLURMD_NODENAME"), "progress": progress,
    }, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--solver", choices=("python", "cpp"), default="python")
    args = parser.parse_args()
    run_segment(args.checkpoint, json.loads(args.ticks.read_text()), args.report, args.solver)


if __name__ == "__main__":
    main()

from __future__ import annotations

from .models import OrbitalJobSpec, PlacementCandidate, PredictedResourceWindow


def feasible(job: OrbitalJobSpec, window: PredictedResourceWindow) -> bool:
    runtime_ms = int(job.runtime_s * 1000)
    if window.end_ms - window.start_ms < runtime_ms:
        return False
    if window.start_ms + runtime_ms > job.submitted_at_ms + int(job.deadline_s * 1000):
        return False
    if window.compute.get("cpus_free", 0) < job.cpus:
        return False
    if window.compute.get("ram_mb_free", 0) < job.ram_mb:
        return False
    if window.energy.get("ending_soc", 0.0) < job.min_soc:
        return False
    if window.thermal.get("predicted_peak_temp_c", 999.0) > job.max_temp_c:
        return False
    if job.required_connectivity and not window.connectivity.get("connected", False):
        return False
    return True


def score_candidate(job: OrbitalJobSpec, window: PredictedResourceWindow) -> float:
    soc_margin = window.energy.get("ending_soc", 0.0) - job.min_soc
    temp_margin = job.max_temp_c - window.thermal.get("predicted_peak_temp_c", job.max_temp_c)
    stability = 1.0 if window.connectivity.get("stable") else 0.0
    survival = window.reliability.get("survival_probability", 0.5)
    duration_margin = (window.end_ms - window.start_ms - job.runtime_s * 1000.0) / 1000.0
    return 0.35 * soc_margin + 0.02 * temp_margin + 0.20 * stability + 0.35 * survival + 0.001 * duration_margin


def generate_candidates(job: OrbitalJobSpec, windows: list[PredictedResourceWindow]) -> list[PlacementCandidate]:
    candidates: list[PlacementCandidate] = []
    for window in windows:
        if not feasible(job, window):
            continue
        score = score_candidate(job, window)
        candidates.append(
            PlacementCandidate(
                job_id=job.job_id,
                nodes=[window.node_id],
                start_ms=window.start_ms,
                predicted_finish_ms=window.start_ms + int(job.runtime_s * 1000),
                score=score,
                predicted_energy_wh=window.energy.get("safe_compute_energy_wh", 0.0),
                predicted_peak_temp_c=window.thermal.get("predicted_peak_temp_c", 0.0),
                survival_probability=window.reliability.get("survival_probability", 0.0),
            )
        )
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def select_candidate(job: OrbitalJobSpec, windows: list[PredictedResourceWindow]) -> PlacementCandidate | None:
    candidates = generate_candidates(job, windows)
    return candidates[0] if candidates else None


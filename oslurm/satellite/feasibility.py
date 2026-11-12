from __future__ import annotations

from dataclasses import dataclass
import math

from oslurm.models import NodeId, OrbitalJobSpec, PredictedResourceWindow, TimestampMs

from .authority import SchedulingIntent
from .decisions import CandidateRejection, RejectionCause
from .reservations import ResourceReservation, ReservationState


@dataclass(frozen=True)
class Candidate:
    node_id: NodeId
    window: PredictedResourceWindow | None
    advertisement: object | None
    is_local: bool
    migration_cost_s: float | None = None


@dataclass(frozen=True)
class FeasibilityResult:
    candidate: Candidate
    feasible: bool
    rejections: list[CandidateRejection]
    predicted_completion_ms: TimestampMs
    migration_cost_s: float
    energy_cost: float


def resource_window_remaining_ms(now: TimestampMs, candidate: Candidate) -> int:
    if candidate.window is not None:
        return max(0, candidate.window.end_ms - max(now, candidate.window.start_ms))
    if candidate.advertisement is not None:
        return max(0, getattr(candidate.advertisement, "stable_until") - now)
    return 0


def candidate_capacity(candidate: Candidate) -> tuple[int, int, float, float, float]:
    if candidate.window is not None:
        compute = candidate.window.compute
        energy = candidate.window.energy
        thermal = candidate.window.thermal
        return (
            int(compute.get("cpus_free", 0)),
            int(compute.get("ram_mb_free", 0)),
            float(energy.get("minimum_soc", energy.get("ending_soc", 0.0))),
            float(thermal.get("predicted_peak_temp_c", 999.0)),
            float(candidate.window.reliability.get("survival_probability", 1.0)),
        )
    ad = candidate.advertisement
    return (
        int(ad.compute.cpus_floor),
        int(ad.compute.ram_mb_floor),
        float(ad.energy.predicted_minimum_soc),
        float(ad.thermal.hard_limit_c - ad.thermal.headroom_c),
        1.0,
    )


def hard_feasibility(
    job: OrbitalJobSpec,
    intent: SchedulingIntent,
    candidate: Candidate,
    now: TimestampMs,
    effective_thermal_limit_c: float,
    reservations: list[ResourceReservation],
) -> FeasibilityResult:
    cpus, ram_mb, min_soc, peak_temp_c, _survival = candidate_capacity(candidate)
    required_ms = int(job.runtime_s * 1000)
    migration_s = 0.0 if candidate.is_local else candidate.migration_cost_s if candidate.migration_cost_s is not None else (27.0 if job.checkpoint_supported else 60.0)
    required_ms += math.ceil(migration_s * 1000)
    predicted_completion = now + required_ms
    deadline = intent.deadline if intent.deadline is not None else job.submitted_at_ms + int(job.deadline_s * 1000)
    rejected: list[CandidateRejection] = []
    if cpus < job.cpus:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.INSUFFICIENT_CPU, cpus, job.cpus))
    if ram_mb < job.ram_mb:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.INSUFFICIENT_MEMORY, ram_mb, job.ram_mb))
    for accel, count in intent.resource_constraints.accelerators.items():
        available = 1
        if candidate.advertisement is not None:
            available = candidate.advertisement.compute.accelerators.get(accel, 0)
        if count > available:
            rejected.append(CandidateRejection(candidate.node_id, RejectionCause.INSUFFICIENT_ACCELERATOR, available, count))
    if predicted_completion > deadline:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.DEADLINE_VIOLATION, predicted_completion, deadline))
    if min_soc < intent.energy_policy.reserve_soc:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.ENERGY_RESERVE_VIOLATION, round(min_soc, 3), intent.energy_policy.reserve_soc))
    if peak_temp_c > effective_thermal_limit_c:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.THERMAL_LIMIT_VIOLATION, round(peak_temp_c, 2), effective_thermal_limit_c))
    if resource_window_remaining_ms(now, candidate) < required_ms:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.CONNECTIVITY_WINDOW_TOO_SHORT, resource_window_remaining_ms(now, candidate) / 1000.0, required_ms / 1000.0))
    if candidate.advertisement is not None and getattr(candidate.advertisement, "valid_until") < now:
        rejected.append(CandidateRejection(candidate.node_id, RejectionCause.ADVERTISEMENT_EXPIRED, getattr(candidate.advertisement, "valid_until"), now))
    for reservation in reservations:
        if reservation.job_id != job.job_id and reservation.state in {ReservationState.ACCEPTED, ReservationState.COMMITTED}:
            rejected.append(CandidateRejection(candidate.node_id, RejectionCause.RESERVATION_UNAVAILABLE, reservation.reservation_id, "free reservation slot"))
    return FeasibilityResult(
        candidate=candidate,
        feasible=not rejected,
        rejections=rejected,
        predicted_completion_ms=predicted_completion,
        migration_cost_s=migration_s,
        energy_cost=job.runtime_s * max(0.0, 1.0 - min_soc),
    )

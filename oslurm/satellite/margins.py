from __future__ import annotations

from oslurm.models import OrbitalJobSpec, TimestampMs

from .authority import SchedulingIntent
from .decisions import DecisionMetrics
from .feasibility import FeasibilityResult, candidate_capacity, resource_window_remaining_ms


def normalized_margins(
    result: FeasibilityResult,
    job: OrbitalJobSpec,
    intent: SchedulingIntent,
    now: TimestampMs,
    effective_thermal_limit_c: float,
) -> DecisionMetrics:
    _cpus, _ram, min_soc, peak_temp_c, _survival = candidate_capacity(result.candidate)
    deadline = intent.deadline if intent.deadline is not None else job.submitted_at_ms + int(job.deadline_s * 1000)
    deadline_margin = max(0.0, (deadline - result.predicted_completion_ms) / max(1.0, job.runtime_s * 1000.0))
    energy_margin = max(0.0, (min_soc - intent.energy_policy.reserve_soc) / max(0.01, 1.0 - intent.energy_policy.reserve_soc))
    thermal_margin = max(0.0, (effective_thermal_limit_c - peak_temp_c) / max(1.0, effective_thermal_limit_c))
    required_ms = result.predicted_completion_ms - now
    connectivity_margin = max(0.0, (resource_window_remaining_ms(now, result.candidate) - required_ms) / max(1.0, required_ms))
    worst = min(deadline_margin, energy_margin, thermal_margin, connectivity_margin)
    return DecisionMetrics(
        deadline_margin=deadline_margin,
        energy_margin=energy_margin,
        thermal_margin=thermal_margin,
        connectivity_margin=connectivity_margin,
        worst_safety_margin=worst,
        predicted_completion_time_s=result.predicted_completion_ms / 1000.0,
        migration_cost=result.migration_cost_s,
        energy_cost=result.energy_cost,
    )

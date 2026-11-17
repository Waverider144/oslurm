"""Host adapter for the allocation-free flight decision ABI."""
from __future__ import annotations

import ctypes as C
import math

from oslurm.cpp import Candidate as NativeCandidate, Request, library
from .decisions import CandidateRejection, DecisionReason, RejectionCause, SchedulingDecision, TieBreaker
from .feasibility import candidate_capacity, hard_feasibility, resource_window_remaining_ms
from .margins import normalized_margins
from .policies import DeterministicSatelliteScheduler


CAUSES = (RejectionCause.INSUFFICIENT_CPU, RejectionCause.INSUFFICIENT_MEMORY,
    RejectionCause.ENERGY_RESERVE_VIOLATION, RejectionCause.THERMAL_LIMIT_VIOLATION,
    RejectionCause.CONNECTIVITY_WINDOW_TOO_SHORT, RejectionCause.DEADLINE_VIOLATION,
    RejectionCause.ADVERTISEMENT_EXPIRED, RejectionCause.RESERVATION_UNAVAILABLE,
    RejectionCause.INSUFFICIENT_ACCELERATOR)


class EmbeddedSatelliteScheduler(DeterministicSatelliteScheduler):
    rule_id = "FIXED_POINT_MAXIMIZE_WORST_SAFETY_MARGIN"

    def on_job_arrival(self, job, intent, ctx):
        if not intent.authority.permits_local_decision(ctx.now, ctx.mission_policy.ground_connected):
            return SchedulingDecision.reject(job.job_id, DecisionReason("AUTHORITY_CHECK", 1,
                [CandidateRejection(ctx.self_state.node_id, RejectionCause.AUTHORITY_VIOLATION, "local decision", "ground authority")]))
        candidates = sorted(self._candidates(ctx), key=lambda c: c.node_id)
        reason = DecisionReason(self.rule_id, len(candidates))
        if not 1 <= len(candidates) <= 16:
            return SchedulingDecision.reject(job.job_id, reason)
        try:
            thermal = ctx.mission_policy.effective_thermal_limit(intent.thermal_policy.max_temperature_c)
            deadline = intent.deadline if intent.deadline is not None else job.submitted_at_ms + int(job.deadline_s * 1000)
            values = (ctx.now, deadline, intent.authority.until or 0)
            if any(not 0 <= value < 2**64 for value in values):
                raise ValueError("invalid clock")
            runtime = int(job.runtime_s * 1000)
            if not 1 <= runtime < 2**32 or not 1 <= job.cpus < 2**32 or not 1 <= job.ram_mb < 2**32:
                raise ValueError("invalid task resources")
            reserve = math.ceil(intent.energy_policy.reserve_soc * 1000000)
            if not 0 <= reserve <= 1000000 or not 1 <= thermal <= 2000:
                raise ValueError("invalid safety limits")
            modes = {"GROUND_REQUIRED": 0, "AUTONOMOUS_UNTIL": 1, "FULLY_AUTONOMOUS": 2}
            allowed = int(intent.allowed_actions.execute_local) | (int(intent.allowed_actions.remote_handoff and intent.allowed_actions.migrate) << 1) | (int(intent.allowed_actions.defer) << 2)
            request = Request(ctx.now, deadline, intent.authority.until or 0, runtime, job.cpus, job.ram_mb,
                reserve, math.floor(thermal * 1000), modes[intent.authority.mode.value],
                ctx.mission_policy.ground_connected, allowed)
            busy = any(r.job_id != job.job_id and r.state.value in {"ACCEPTED", "COMMITTED"} for r in ctx.reservations)
            native = []
            for candidate in candidates:
                cpu, ram, soc, peak, _ = candidate_capacity(candidate)
                migration = 0 if candidate.is_local else candidate.migration_cost_s if candidate.migration_cost_s is not None else (27 if job.checkpoint_supported else 60)
                migration_ms = math.ceil(migration * 1000)
                if (not 0 <= soc <= 1 or not -273.15 <= peak <= 2000 or
                        not 0 <= cpu < 2**32 or not 0 <= ram < 2**32 or not 0 <= migration_ms < 2**32):
                    raise ValueError("invalid candidate snapshot")
                valid = candidate.advertisement.valid_until if candidate.advertisement else 2**64 - 1
                window = int(resource_window_remaining_ms(ctx.now, candidate))
                if not 0 <= valid < 2**64 or not 0 <= window < 2**64:
                    raise ValueError("invalid advertisement/window")
                accelerators = candidate.advertisement.compute.accelerators if candidate.advertisement else {}
                accelerator_ok = all(count <= (accelerators.get(name, 0) if candidate.advertisement else 1)
                                     for name, count in intent.resource_constraints.accelerators.items())
                native.append(NativeCandidate(window, valid, cpu, ram, math.floor(soc * 1000000),
                    math.ceil(peak * 1000), migration_ms, candidate.is_local, busy, accelerator_ok))
            array = (NativeCandidate * len(native))(*native)
            decision = library().oslurm_decide(C.byref(request), array, len(native))
        except (ValueError, OverflowError, AttributeError, TypeError, KeyError):
            return SchedulingDecision.reject(job.job_id, reason)
        rejected = [CandidateRejection(candidate.node_id, cause, "C++ gate", "safe resource envelope")
                    for i, candidate in enumerate(candidates) for bit, cause in enumerate(CAUSES)
                    if decision.rejected[i] & (1 << bit)]
        reason = DecisionReason(self.rule_id, len(candidates), rejected)
        if decision.action in (3, 4):
            return SchedulingDecision.reject(job.job_id, reason)
        if decision.action == 2:
            return SchedulingDecision.defer(job.job_id, ctx.now + 60000, reason)
        selected = candidates[decision.selected]
        reference = hard_feasibility(job, intent, selected, ctx.now, thermal, ctx.reservations)
        if not reference.feasible:
            return SchedulingDecision.reject(job.job_id, reason)
        reason = DecisionReason(self.rule_id, len(candidates), rejected,
                                normalized_margins(reference, job, intent, ctx.now, thermal),
                                [TieBreaker("node_id", selected.node_id)])
        return (SchedulingDecision.execute_local(job.job_id, reason) if decision.action == 0 else
                SchedulingDecision.offer_remote(job.job_id, selected.node_id, reason))

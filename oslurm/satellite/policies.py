from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from oslurm.models import OrbitEvent, OrbitalJobSpec

from .advertisement import SatelliteSchedulingAdvertisement
from .context import ConnectivityMode, LocalSchedulingContext
from .decisions import CandidateRejection, DecisionReason, RejectionCause, SchedulingDecision, SchedulingDecisionType, TieBreaker
from .feasibility import Candidate, hard_feasibility
from .margins import normalized_margins
from .protocol import TaskAcceptance, TaskOffer, TaskOfferDecision, TaskOfferDecisionType, TaskReject
from .reservations import ReservationState, ResourceEnvelope, ResourceReservation


class SatelliteScheduler(Protocol):
    def on_job_arrival(self, job: OrbitalJobSpec, intent: object, ctx: LocalSchedulingContext) -> SchedulingDecision: ...
    def on_orbital_event(self, event: OrbitEvent, ctx: LocalSchedulingContext) -> list[SchedulingDecision]: ...
    def on_neighbor_advertisement(self, advertisement: SatelliteSchedulingAdvertisement, ctx: LocalSchedulingContext) -> list[SchedulingDecision]: ...
    def on_task_offer(self, offer: TaskOffer, ctx: LocalSchedulingContext) -> TaskOfferDecision: ...
    def on_partition_change(self, ctx: LocalSchedulingContext) -> list[SchedulingDecision]: ...


class DeterministicSatelliteScheduler:
    rule_id = "MAXIMIZE_WORST_SAFETY_MARGIN"

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.reservations: dict[str, ResourceReservation] = {}
        self.committed_offers: set[str] = set()

    def on_job_arrival(self, job: OrbitalJobSpec, intent: object, ctx: LocalSchedulingContext) -> SchedulingDecision:
        if not intent.authority.permits_local_decision(ctx.now, ctx.mission_policy.ground_connected):
            reason = DecisionReason(
                "AUTHORITY_CHECK",
                1,
                [CandidateRejection(ctx.self_state.node_id, RejectionCause.AUTHORITY_VIOLATION, "local decision", "ground authority")],
            )
            return SchedulingDecision.reject(job.job_id, reason)
        candidates = self._candidates(ctx)
        feasible = []
        rejections = []
        thermal_limit = ctx.mission_policy.effective_thermal_limit(intent.thermal_policy.max_temperature_c)
        for candidate in candidates:
            result = hard_feasibility(job, intent, candidate, ctx.now, thermal_limit, ctx.reservations)
            if result.feasible:
                metrics = normalized_margins(result, job, intent, ctx.now, thermal_limit)
                feasible.append((candidate, result, metrics))
            else:
                rejections.extend(result.rejections)
        if not feasible:
            reason = DecisionReason(self.rule_id, len(candidates), rejections)
            if intent.allowed_actions.defer:
                return SchedulingDecision.defer(job.job_id, ctx.now + 60_000, reason)
            return SchedulingDecision.reject(job.job_id, reason)
        candidate, _result, metrics = sorted(
            feasible,
            key=lambda item: (
                -item[2].worst_safety_margin,
                item[2].predicted_completion_time_s,
                item[2].migration_cost,
                item[2].energy_cost,
                item[0].node_id,
            ),
        )[0]
        reason = DecisionReason(
            self.rule_id,
            len(candidates),
            rejections,
            metrics,
            [TieBreaker("node_id", candidate.node_id)],
        )
        if candidate.is_local:
            if intent.allowed_actions.execute_local:
                return SchedulingDecision.execute_local(job.job_id, reason)
            return SchedulingDecision.defer(job.job_id, ctx.now + 60_000, reason)
        if intent.allowed_actions.remote_handoff and intent.allowed_actions.migrate:
            return SchedulingDecision.offer_remote(job.job_id, candidate.node_id, reason)
        return SchedulingDecision.defer(job.job_id, ctx.now + 60_000, reason)

    def on_orbital_event(self, event: OrbitEvent, ctx: LocalSchedulingContext) -> list[SchedulingDecision]:
        decisions = []
        for running in ctx.running_jobs:
            if event.node_id != ctx.self_state.node_id:
                continue
            decision = self.on_job_arrival(
                replace(running.job, runtime_s=running.remaining_runtime_s),
                running.intent,
                ctx,
            )
            if decision.decision_type == SchedulingDecisionType.OFFER_REMOTE and running.intent.allowed_actions.checkpoint:
                decisions.append(SchedulingDecision.checkpoint(running.job.job_id, decision.reason))
                decisions.append(decision)
            else:
                decisions.append(decision)
        return decisions

    def on_neighbor_advertisement(self, advertisement: SatelliteSchedulingAdvertisement, ctx: LocalSchedulingContext) -> list[SchedulingDecision]:
        accepted = ctx.neighbors.update(advertisement)
        if not accepted:
            reason = DecisionReason("IGNORE_STALE_ADVERTISEMENT", 1)
            return [SchedulingDecision.defer("advertisement", ctx.now, reason)]
        return []

    def on_task_offer(self, offer: TaskOffer, ctx: LocalSchedulingContext) -> TaskOfferDecision:
        if offer.expires_at < ctx.now:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "offer expired", offer.sequence),
            )
        window = ctx.own_windows[0]
        if window.compute.get("cpus_free", 0) < offer.task.cpus:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "insufficient cpu", offer.sequence),
            )
        if window.compute.get("ram_mb_free", 0) < offer.task.ram_mb:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "insufficient memory", offer.sequence),
            )
        if window.energy.get("minimum_soc", ctx.self_state.energy.soc) < ctx.self_state.energy.reserve_soc:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "energy reserve", offer.sequence),
            )
        if window.thermal.get("predicted_peak_temp_c", ctx.self_state.thermal.temperature_c) > ctx.mission_policy.hardware_thermal_hard_limit_c:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "thermal hard limit", offer.sequence),
            )
        if window.end_ms - ctx.now < offer.required_window_ms:
            return TaskOfferDecision(
                TaskOfferDecisionType.REJECT,
                rejection=TaskReject(f"reject:{offer.offer_id}", offer.offer_id, ctx.self_state.node_id, "window too short", offer.sequence),
            )
        reservation_id = f"R-{ctx.self_state.node_id}-{offer.sequence}"
        envelope = ResourceEnvelope(
            cpus=offer.task.cpus,
            ram_mb=offer.task.ram_mb,
            compute_units_per_s=1.0,
            minimum_soc=window.energy.get("minimum_soc", ctx.self_state.energy.soc),
            thermal_headroom_c=ctx.self_state.thermal.hard_limit_c - window.thermal.get("predicted_peak_temp_c", ctx.self_state.thermal.temperature_c),
        )
        self.reservations[reservation_id] = ResourceReservation(
            reservation_id=reservation_id,
            job_id=offer.task.job_id,
            source=offer.source,
            reserved_resources=envelope,
            created_at=ctx.now,
            expires_at=min(ctx.now + 5_000, offer.expires_at),
            state=ReservationState.ACCEPTED,
        )
        return TaskOfferDecision(
            TaskOfferDecisionType.ACCEPT,
            acceptance=TaskAcceptance(
                message_id=f"accept:{offer.offer_id}",
                offer_id=offer.offer_id,
                reservation_id=reservation_id,
                destination=ctx.self_state.node_id,
                valid_until=min(ctx.now + 5_000, offer.expires_at),
                earliest_start=ctx.now,
                predicted_finish=ctx.now + offer.required_window_ms,
                guaranteed_resource_floor=envelope,
                sequence=offer.sequence,
            ),
        )

    def on_partition_change(self, ctx: LocalSchedulingContext) -> list[SchedulingDecision]:
        decisions = []
        for running in ctx.running_jobs:
            if ctx.connectivity == ConnectivityMode.ISOLATED and running.intent.allowed_actions.defer:
                reason = DecisionReason("PARTITION_LOCAL_ONLY", 1)
                decisions.append(SchedulingDecision.defer(running.job.job_id, ctx.now + 30_000, reason))
        return decisions

    def commit_reservation(self, offer_id: str, reservation_id: str, now: int) -> bool:
        if offer_id in self.committed_offers:
            return False
        reservation = self.reservations.get(reservation_id)
        if reservation is None or reservation.expire_if_needed(now) or reservation.state != ReservationState.ACCEPTED:
            return False
        reservation.state = ReservationState.COMMITTED
        self.committed_offers.add(offer_id)
        return True

    def expire_reservations(self, now: int) -> int:
        expired = 0
        for reservation in self.reservations.values():
            expired += int(reservation.expire_if_needed(now))
        return expired

    def _candidates(self, ctx: LocalSchedulingContext) -> list[Candidate]:
        candidates = [Candidate(ctx.self_state.node_id, ctx.own_windows[0] if ctx.own_windows else None, None, True)]
        if ctx.connectivity != ConnectivityMode.ISOLATED:
            reachable_nodes = {link.target for link in ctx.self_state.links}
            for ad in ctx.neighbors.reachable(ctx.now, reachable_nodes):
                candidates.append(Candidate(ad.node_id, None, ad, False))
        return candidates

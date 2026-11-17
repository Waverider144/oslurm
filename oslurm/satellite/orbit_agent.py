"""Bounded satellite-local decisions for the real checkpointable orbit workload."""
from __future__ import annotations

import math
from dataclasses import asdict

from oslurm.models import ComputeState, EnergyState, OrbitState, OrbitalJobSpec, OrbitalNodeState, PredictedResourceWindow, ThermalState, WindowTerminationCause
from .advertisement import generate_advertisement
from .authority import AllowedActions, AuthorityPolicy, EnergyPolicy, MissionPolicy, ResiliencePolicy, ResourceConstraints, SchedulingIntent, ThermalPolicy
from .context import ConnectivityMode, LocalSchedulingContext
from .decisions import SchedulingDecisionType
from .neighbor_table import NeighborSchedulingTable
from .policies import DeterministicSatelliteScheduler
from .protocol import CheckpointDescriptor, ProtocolEngine, TaskCommit, TaskOffer, TaskOfferDecisionType, TaskSummary


class OrbitAutonomy:
    def __init__(self, telemetry, emit, horizon_s, disconnect_s=240, authority_until_s=None, decision_core="python"):
        self.telemetry, self.emit, self.horizon_s = telemetry, emit, horizon_s
        self.disconnect_s = disconnect_s
        self.authority_until_s = horizon_s if authority_until_s is None else authority_until_s
        scheduler = DeterministicSatelliteScheduler
        if decision_core == "cpp":
            from .embedded import EmbeddedSatelliteScheduler
            scheduler = EmbeddedSatelliteScheduler
        elif decision_core != "python":
            raise ValueError("unsupported decision core")
        self.decision_core = decision_core
        self.schedulers = {node: scheduler(node) for node in telemetry.nodes}
        self.protocols = {node: ProtocolEngine() for node in telemetry.nodes}
        self.decisions = self.handoffs = 0
        self.rejections = 0

    def context(self, node, at_s, peer_delays=None, neighbors=None):
        t = self.telemetry
        now = t.epoch_ms + round(at_s * 1000)
        orbit = t.orbit(node, at_s)
        state = t.state[node]
        forecast = t.forecast(node, min(300, self.horizon_s - at_s))
        window = PredictedResourceWindow(
            f"{node}:{now}", node, now, min(t.epoch_ms + round(self.horizon_s * 1000), now + 300_000), now, 0.8,
            {"cpus_free": 1, "ram_mb_free": 512}, {"minimum_soc": forecast["minimum_soc"]},
            {"predicted_peak_temp_c": forecast["predicted_peak_temp_c"]},
            {"connected": True}, {"survival_probability": 1}, [WindowTerminationCause.HORIZON])
        self_state = OrbitalNodeState(
            node, now, OrbitState(tuple(orbit["position_eci_m"]), tuple(orbit["velocity_eci_mps"]), orbit["in_sunlight"]),
            ComputeState(1, 1, 512, 512), EnergyState(t.power.battery_capacity_wh, state["soc"], t.power.reserve_soc),
            ThermalState(state["temperature_c"], t.thermal.soft_limit_c, t.thermal.hard_limit_c),
            [], {}, {"mode": "modeled"}, {}, {"agent": "satellite-local"})
        connected = at_s < self.disconnect_s
        return LocalSchedulingContext(
            now, self_state, [window], neighbors or NeighborSchedulingTable(),
            connectivity=ConnectivityMode.FULLY_CONNECTED if connected else ConnectivityMode.GROUND_DISCONNECTED,
            mission_policy=MissionPolicy(t.thermal.hard_limit_c, connected), peer_delivery_s=peer_delays or {})

    def decide(self, source, at_s, plans, sequence):
        t = self.telemetry
        now = t.epoch_ms + round(at_s * 1000)
        quantum = min(120, self.horizon_s - at_s)
        job = OrbitalJobSpec("AXB001", now, quantum, self.horizon_s - at_s, 1, 512,
                             t.power.reserve_soc, t.thermal.soft_limit_c)
        intent = SchedulingIntent(
            job.job_id, now, t.epoch_ms + round(self.horizon_s * 1000), 90,
            ResourceConstraints(1, 512, {}), EnergyPolicy(t.power.reserve_soc), ThermalPolicy(t.thermal.soft_limit_c),
            ResiliencePolicy(), AllowedActions(), AuthorityPolicy.autonomous_until(t.epoch_ms + round(self.authority_until_s * 1000)), 1)
        neighbors = NeighborSchedulingTable()
        local_safe = t.can_compute(source, quantum)
        # Avoid migration churn while the current sunlit window remains safe.
        consider_peers = not t.orbit(source, at_s)["in_sunlight"] or not local_safe
        delays = {}
        if consider_peers:
            for peer, plan in plans.items():
                if plan.predicted_finish_s > self.authority_until_s and at_s >= self.disconnect_s:
                    continue
                ad = generate_advertisement(self.context(peer, at_s).self_state,
                                            self.context(peer, at_s).own_windows[0], now, sequence)
                neighbors.update(ad)
                delays[peer] = plan.predicted_finish_s - at_s
                self.emit(at_s, "ADVERTISEMENT_RECEIVED", "SATELLITE_AGENT", source,
                          peer=peer, sequence=ad.sequence, valid_until=ad.valid_until,
                          route_kind=plan.path_kind.value, telemetry_source=t.source)
        ctx = self.context(source, at_s, delays, neighbors)
        decision = self.schedulers[source].on_job_arrival(job, intent, ctx)
        self.decisions += 1
        rejected = [{"node_id": rejection.node_id, "feasible": False,
                     "rejection_causes": [rejection.cause.value], "observed": rejection.observed,
                     "required": rejection.required} for rejection in decision.reason.rejected_candidates]
        self.rejections += len(rejected)
        selected = decision.peer if decision.decision_type == SchedulingDecisionType.OFFER_REMOTE else source
        changed = selected != source
        payload = {"local_node": source, "decision_type": decision.decision_type.value,
                   "decision_rule": decision.reason.rule,
                   "selected_metrics": asdict(decision.reason.selected_metrics) if decision.reason.selected_metrics else None,
                   "authority_until_s": self.authority_until_s, "ground_connected": ctx.mission_policy.ground_connected,
                   "connectivity": ctx.connectivity.value, "candidate_results": rejected + [
                       {"node_id": selected, "feasible": decision.decision_type in {SchedulingDecisionType.EXECUTE_LOCAL, SchedulingDecisionType.OFFER_REMOTE}}],
                   "candidates_feasible": int(decision.decision_type in {SchedulingDecisionType.EXECUTE_LOCAL, SchedulingDecisionType.OFFER_REMOTE}),
                   "selected_action": {"type": decision.decision_type.value, "node_id": selected, "changed": changed},
                   "previous_node": source, "trigger": "LOCAL_STATE_REEVALUATION", "quantum_s": quantum}
        return decision, selected, intent, payload

    def negotiate(self, source, target, at_s, plan, intent, size, sequence):
        ctx = self.context(target, at_s)
        now = ctx.now
        offer = TaskOffer(f"offer:{sequence}", f"AXB001:{source}:{target}:{sequence}", source,
                          TaskSummary("AXB001", 1, 512, True), 120, intent.deadline,
                          CheckpointDescriptor(f"AXB001:cp:{sequence}", size, 0),
                          math.ceil((min(120, self.horizon_s - at_s) + plan.predicted_finish_s - at_s) * 1000),
                          "orbit-intent-v1", now, now + 5000, sequence)
        self.emit(at_s, "TASK_OFFER_SENT", "SATELLITE_AGENT", source, destination=target, offer_id=offer.offer_id)
        reply = self.schedulers[target].on_task_offer(offer, ctx)
        if reply.decision_type != TaskOfferDecisionType.ACCEPT:
            self.emit(at_s, "TASK_REJECT", "SATELLITE_AGENT", target, offer_id=offer.offer_id,
                      reason=reply.rejection.reason)
            return False
        acceptance = reply.acceptance
        self.emit(at_s, "TASK_ACCEPT_RECEIVED", "SATELLITE_AGENT", source,
                  reservation_id=acceptance.reservation_id, peer=target)
        commit = TaskCommit(f"commit:{sequence}", offer.offer_id, acceptance.reservation_id,
                            source, offer.checkpoint, sequence)
        if not self.schedulers[target].commit_reservation(commit.offer_id, commit.reservation_id, now):
            return False
        if not self.protocols[target].commit_once(commit):
            return False
        self.handoffs += 1
        self.emit(at_s, "TASK_COMMIT", "SATELLITE_AGENT", target,
                  offer_id=offer.offer_id, reservation_id=acceptance.reservation_id,
                  control_transport="in-process simulated messages")
        return True

    def metrics(self):
        return {"autonomous_decisions": self.decisions, "committed_handoffs": self.handoffs,
                "candidate_rejections": self.rejections, "ground_dependent_decisions": 0,
                "ground_disconnect_s": self.disconnect_s, "authority_until_s": self.authority_until_s,
                "core": "C++ fixed-capacity flight ABI" if self.decision_core == "cpp" else "DeterministicSatelliteScheduler",
                "decision_core": self.decision_core, "protocol_transport": "in-process simulation"}

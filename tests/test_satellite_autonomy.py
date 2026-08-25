import unittest
from dataclasses import replace

from oslurm.models import ComputeState, EnergyState, LinkState, OrbitEvent, OrbitState, OrbitalJobSpec, OrbitalNodeState, PredictedResourceWindow, ThermalState
from oslurm.satellite.advertisement import generate_advertisement
from oslurm.satellite.authority import (
    AllowedActions,
    AuthorityPolicy,
    EnergyPolicy,
    MissionPolicy,
    ResiliencePolicy,
    ResourceConstraints,
    SchedulingIntent,
    ThermalPolicy,
    merge_intent,
)
from oslurm.satellite.context import ConnectivityMode, LocalSchedulingContext, RunningJob
from oslurm.satellite.decisions import RejectionCause, SchedulingDecisionType
from oslurm.satellite.execution import LocalExecutionBackend
from oslurm.satellite.feasibility import Candidate, hard_feasibility
from oslurm.satellite.journal import ExecutionEvent, ExecutionJournal
from oslurm.satellite.neighbor_table import NeighborSchedulingTable
from oslurm.satellite.policies import DeterministicSatelliteScheduler
from oslurm.satellite.protocol import CheckpointDescriptor, ProtocolEngine, TaskCommit, TaskOffer, TaskOfferDecisionType, TaskSummary


def node(node_id: str, links: tuple[str, ...] = (), soc: float = 0.6, temp: float = 42.0) -> OrbitalNodeState:
    return OrbitalNodeState(
        node_id=node_id,
        observed_at_ms=0,
        orbit=OrbitState((1.0, 2.0, 3.0), (0.1, 0.2, 0.3), True),
        compute=ComputeState(4, 4, 8192, 8192, {"gpu": 0}),
        energy=EnergyState(500.0, soc, 0.35),
        thermal=ThermalState(temp, 72.0, 80.0),
        links=[LinkState(target, 1_000_000, 20.0) for target in links],
        storage={},
        health={},
        failure_domains={"plane": node_id[-1]},
        scheduler={},
    )


def window(node_id: str, start: int = 0, duration_s: float = 300.0, soc: float = 0.55, peak: float = 55.0, cpus: int = 4) -> PredictedResourceWindow:
    return PredictedResourceWindow(
        window_id=f"{node_id}-{start}",
        node_id=node_id,
        start_ms=start,
        end_ms=start + int(duration_s * 1000),
        predicted_at_ms=start,
        confidence=0.9,
        compute={"cpus_free": cpus, "ram_mb_free": 8192, "accelerators": {"gpu": 0}},
        energy={"minimum_soc": soc, "ending_soc": soc},
        thermal={"predicted_peak_temp_c": peak},
        connectivity={"connected": True, "stable": True},
        reliability={"survival_probability": 0.99},
        termination_causes=[],
    )


def job(runtime_s: float = 120.0) -> OrbitalJobSpec:
    return OrbitalJobSpec("381", 0, runtime_s, 600.0, 2, 512, 0.35, 72.0, checkpoint_supported=True)


def intent(spec: OrbitalJobSpec | None = None, authority=None, actions=None, version: int = 1) -> SchedulingIntent:
    spec = spec or job()
    return SchedulingIntent(
        job_id=spec.job_id,
        issued_at=0,
        deadline=int(spec.deadline_s * 1000),
        priority=10,
        resource_constraints=ResourceConstraints(spec.cpus, spec.ram_mb, {}),
        energy_policy=EnergyPolicy(spec.min_soc),
        thermal_policy=ThermalPolicy(spec.max_temp_c),
        resilience_policy=ResiliencePolicy(),
        allowed_actions=actions or AllowedActions(),
        authority=authority or AuthorityPolicy.autonomous_until(1_000_000),
        intent_version=version,
    )


class SatelliteAutonomyTests(unittest.TestCase):
    def test_advertisement_is_compact_and_stale_updates_are_rejected(self):
        table = NeighborSchedulingTable()
        ad1 = generate_advertisement(node("SAT03"), window("SAT03"), 0, sequence=2)
        stale = replace(ad1, sequence=1)
        self.assertTrue(table.update(ad1))
        self.assertFalse(table.update(stale))
        self.assertEqual(table.stale_rejected, 1)
        self.assertGreater(ad1.compact_size_bytes(), 0)

    def test_hard_feasibility_explains_resource_rejections(self):
        spec = job()
        result = hard_feasibility(spec, intent(spec), Candidate("SAT02", window("SAT02", soc=0.31, cpus=1), None, True), 0, 72.0, [])
        causes = {rejection.cause for rejection in result.rejections}
        self.assertIn(RejectionCause.INSUFFICIENT_CPU, causes)
        self.assertIn(RejectionCause.ENERGY_RESERVE_VIOLATION, causes)

    def test_scheduler_uses_direct_neighbors_only_and_selects_best_margin(self):
        table = NeighborSchedulingTable()
        sat01 = node("SAT01", links=("SAT02", "SAT03"))
        table.update(generate_advertisement(node("SAT02"), window("SAT02", soc=0.34), 0, 1))
        table.update(generate_advertisement(node("SAT03"), window("SAT03", soc=0.56), 0, 1))
        table.update(generate_advertisement(node("SAT04"), window("SAT04", soc=0.80), 0, 1))
        ctx = LocalSchedulingContext(0, sat01, [window("SAT01", duration_s=30.0, soc=0.50)], table)
        decision = DeterministicSatelliteScheduler("SAT01").on_job_arrival(job(), intent(), ctx)
        self.assertEqual(decision.decision_type, SchedulingDecisionType.OFFER_REMOTE)
        self.assertEqual(decision.peer, "SAT03")
        self.assertEqual(decision.reason.tie_breakers[0].value, "SAT03")

    def test_deterministic_tie_breaker_prefers_stable_node_id_order(self):
        table = NeighborSchedulingTable()
        sat01 = node("SAT01", links=("SAT03", "SAT02"))
        table.update(generate_advertisement(node("SAT03"), window("SAT03", soc=0.56), 0, 1))
        table.update(generate_advertisement(node("SAT02"), window("SAT02", soc=0.56), 0, 1))
        ctx = LocalSchedulingContext(0, sat01, [window("SAT01", duration_s=30.0, soc=0.50)], table)
        decision = DeterministicSatelliteScheduler("SAT01").on_job_arrival(job(), intent(), ctx)
        self.assertEqual(decision.peer, "SAT02")

    def test_ground_required_authority_rejects_when_ground_is_disconnected(self):
        ctx = LocalSchedulingContext(0, node("SAT01"), [window("SAT01")], NeighborSchedulingTable(), mission_policy=MissionPolicy(80.0, ground_connected=False))
        decision = DeterministicSatelliteScheduler("SAT01").on_job_arrival(job(), intent(authority=AuthorityPolicy.ground_required()), ctx)
        self.assertEqual(decision.decision_type, SchedulingDecisionType.REJECT)
        self.assertEqual(decision.reason.rejected_candidates[0].cause, RejectionCause.AUTHORITY_VIOLATION)

    def test_task_offer_reservation_commit_is_idempotent(self):
        scheduler = DeterministicSatelliteScheduler("SAT03")
        offer = TaskOffer("m1", "o1", "SAT01", TaskSummary("381", 2, 512, True), 100.0, 300_000, None, 120_000, "i1", 0, 5_000, 1)
        ctx = LocalSchedulingContext(0, node("SAT03"), [window("SAT03", duration_s=200.0, soc=0.55)], NeighborSchedulingTable())
        response = scheduler.on_task_offer(offer, ctx)
        self.assertEqual(response.decision_type, TaskOfferDecisionType.ACCEPT)
        self.assertTrue(scheduler.commit_reservation(offer.offer_id, response.acceptance.reservation_id, 1_000))
        self.assertFalse(scheduler.commit_reservation(offer.offer_id, response.acceptance.reservation_id, 1_100))

    def test_offer_rejects_short_or_unsafe_window(self):
        scheduler = DeterministicSatelliteScheduler("SAT03")
        offer = TaskOffer("m1", "o1", "SAT01", TaskSummary("381", 2, 512, True), 100.0, 300_000, None, 120_000, "i1", 0, 5_000, 1)
        ctx = LocalSchedulingContext(0, node("SAT03"), [window("SAT03", duration_s=40.0, soc=0.55)], NeighborSchedulingTable())
        self.assertEqual(scheduler.on_task_offer(offer, ctx).decision_type, TaskOfferDecisionType.REJECT)
        hot = LocalSchedulingContext(0, node("SAT03"), [window("SAT03", duration_s=200.0, soc=0.55, peak=81.0)], NeighborSchedulingTable())
        self.assertEqual(scheduler.on_task_offer(offer, hot).rejection.reason, "thermal hard limit")

    def test_orbital_event_triggers_predictive_checkpoint_and_handoff(self):
        table = NeighborSchedulingTable()
        sat01 = node("SAT01", links=("SAT03",))
        table.update(generate_advertisement(node("SAT03"), window("SAT03", duration_s=300.0, soc=0.56), 10_000, 1))
        spec = job(runtime_s=300.0)
        running = RunningJob(spec, intent(spec), 0, 128.4, 0.61)
        ctx = LocalSchedulingContext(10_000, sat01, [window("SAT01", start=10_000, duration_s=60.0, soc=0.40)], table, running_jobs=[running])
        decisions = DeterministicSatelliteScheduler("SAT01").on_orbital_event(OrbitEvent("ECLIPSE_ENTRY", "SAT01", 10_000), ctx)
        self.assertEqual([decision.decision_type for decision in decisions], [SchedulingDecisionType.CHECKPOINT, SchedulingDecisionType.OFFER_REMOTE])

    def test_isolated_partition_defers_without_remote_state(self):
        spec = job()
        running = RunningJob(spec, intent(spec), 0, 20.0, 0.8)
        ctx = LocalSchedulingContext(10_000, node("SAT01"), [window("SAT01")], NeighborSchedulingTable(), running_jobs=[running], connectivity=ConnectivityMode.ISOLATED)
        decision = DeterministicSatelliteScheduler("SAT01").on_partition_change(ctx)[0]
        self.assertEqual(decision.decision_type, SchedulingDecisionType.DEFER)

    def test_journal_and_execution_backend_are_replayable(self):
        journal = ExecutionJournal()
        journal.append(0, "381", ExecutionEvent.JOB_STARTED)
        journal.append(1, "381", ExecutionEvent.CHECKPOINT_CREATED)
        self.assertEqual([entry.sequence for entry in journal.sync_since(0)], [1, 2])
        backend = LocalExecutionBackend("SAT01")
        backend.execute("381", 100.0)
        checkpoint_id = backend.checkpoint("381", 0.61)
        self.assertEqual(checkpoint_id, "381:ckpt:0.610")
        backend.restore("381", 0.61)
        backend.complete("381")
        self.assertIn("381", backend.completed)

    def test_protocol_engine_starts_committed_task_once(self):
        protocol = ProtocolEngine()
        commit = TaskCommit("m2", "o2", "r2", "SAT01", CheckpointDescriptor("381:ckpt:0.610", 1024, 0.61), 2)
        self.assertTrue(protocol.commit_once(commit))
        self.assertFalse(protocol.commit_once(commit))
        self.assertEqual(protocol.started_tasks, {"381"})

    def test_newer_intent_replaces_stale_intent(self):
        current = intent(version=2)
        older = intent(version=1)
        newer = intent(version=3)
        self.assertIs(merge_intent(current, older), current)
        self.assertIs(merge_intent(current, newer), newer)

    def test_core_scheduler_has_no_provider_or_slurm_imports(self):
        import inspect
        import oslurm.satellite.policies as policies

        source = inspect.getsource(policies)
        self.assertNotIn("providers.gmat", source)
        self.assertNotIn("SlurmBridge", source)


if __name__ == "__main__":
    unittest.main()

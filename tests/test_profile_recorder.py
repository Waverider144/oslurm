import json
import tempfile
import unittest
from pathlib import Path

from oslurm.cli import OslurmCli
from oslurm.montecarlo import derive_seed
from oslurm.profile.analysis import ProfileAnalyzer
from oslurm.profile.recorder import FlightRecorder, ProfilingConfig
from oslurm.profile.replay import replay_trace
from oslurm.profile.schema import TRACE_SCHEMA_VERSION, TraceEventType


class FlightRecorderTests(unittest.TestCase):
    def test_trace_ordering_schema_and_serialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = FlightRecorder("ordering", root=root, config=ProfilingConfig(mode="full"))
            first = recorder.emit(TraceEventType.JOB_SUBMITTED, 10, job_id="JOB381")
            second = recorder.emit(TraceEventType.JOB_STARTED, 10, job_id="JOB381", parent_event_id=first.header.event_id)
            recorder.close()

            self.assertEqual(first.schema_version, TRACE_SCHEMA_VERSION)
            self.assertLess(first.header.sequence, second.header.sequence)
            events = (root / "profiles" / "ordering" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            decoded = [json.loads(line) for line in events]
            self.assertEqual(decoded[0]["header"]["event_type"], "JOB_SUBMITTED")
            self.assertEqual(decoded[1]["header"]["parent_event_id"], first.header.event_id)

    def test_span_timing_and_overhead_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = FlightRecorder("span", root=Path(tmp))
            with recorder.span("scheduler.feasibility", 0, job_id="JOB381"):
                sum(range(10))
            recorder.close()
            metrics = json.loads((Path(tmp) / "profiles" / "span" / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["events_emitted"], 2)
            self.assertIn("scheduler.feasibility", metrics["spans"])
            self.assertGreater(metrics["profiler_wall_overhead_ns"], 0)

    def test_topology_delta_snapshot_and_replay_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = FlightRecorder("replay", root=root)
            recorder.snapshot(0, {"topology_edges": ["SAT01-SAT02"], "nodes": {}, "jobs": {}})
            recorder.emit(TraceEventType.TOPOLOGY_EDGE_ADDED, 1, payload={"edge_id": "SAT02-SAT03"})
            recorder.emit(TraceEventType.TOPOLOGY_EDGE_REMOVED, 2, payload={"edge_id": "SAT01-SAT02"})
            recorder.emit(TraceEventType.NODE_OPERATING_SNAPSHOT, 3, node_id="SAT02", payload={"soc": 0.5})
            recorder.emit(TraceEventType.JOB_COMPLETED, 4, job_id="JOB381")
            recorder.close()
            result = replay_trace(root / "profiles" / "replay")
            self.assertEqual(result.event_count, 6)
            self.assertTrue(result.final_topology_hash)
            self.assertTrue(result.final_node_state_digest)
            self.assertTrue(result.final_job_state_digest)

    def test_scheduler_attribution_bottleneck_and_stranded_compute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = FlightRecorder("analysis", root=root)
            recorder.emit(TraceEventType.NODE_OPERATING_SNAPSHOT, 0, node_id="SAT01", payload={"available_cpu": 4, "schedulable_compute": 2, "cpu_utilization": 0.5})
            recorder.emit(TraceEventType.SCHEDULER_DECISION, 1, job_id="JOB381", payload={
                "trigger": "TOPOLOGY_CHANGE",
                "candidates_feasible": 1,
                "candidate_results": [{"node_id": "SAT02", "feasible": False, "rejection_causes": ["TOPOLOGY"]}],
                "selected_action": {"changed": False},
                "cost": {"wall_time_ns": 100, "candidates_evaluated": 2},
            })
            recorder.emit(TraceEventType.OPERATING_REGIME_ENTER, 2, job_id="JOB381", node_id="SAT01", payload={"regime": "TOPOLOGY_LIMITED"})
            recorder.emit(TraceEventType.OPERATING_REGIME_EXIT, 12, job_id="JOB381", node_id="SAT01", payload={"regime": "TOPOLOGY_LIMITED", "duration_ns": 10})
            recorder.close()

            analyzer = ProfileAnalyzer(root / "profiles" / "analysis")
            self.assertEqual(analyzer.scheduler_metrics()["candidate_rejection"]["TOPOLOGY"], 100.0)
            self.assertEqual(analyzer.bottleneck_summary()["dominant"], "TOPOLOGY")
            self.assertEqual(analyzer.constellation_utilization()["topology_stranded_compute"], 2)

    def test_cli_state_and_profile_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = OslurmCli(Path(tmp))
            self.assertIn("profile on", cli.execute("profile on --run-id cli-test --mode light"))
            self.assertIn("profile active", cli.execute("profile status"))
            self.assertIn("live topology", cli.execute("state topology"))
            self.assertIn("profile off", cli.execute("profile off"))

    def test_master_seed_derivation_is_reproducible(self):
        self.assertEqual(derive_seed(42, 1), derive_seed(42, 1))
        self.assertNotEqual(derive_seed(42, 1), derive_seed(42, 2))


if __name__ == "__main__":
    unittest.main()

import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oslurm.joint_execution import run_joint_axb
from oslurm.network.dynamic import dynamic_network
from oslurm.network.ground import above_mask, ground_state, with_ground_sites
from oslurm.network.runtime import MultiConstellationRuntime
from oslurm.profile.analysis import ProfileAnalyzer


EPOCH = 1787356800000
SITE = {"latitude_deg": 0, "longitude_deg": 0, "altitude_m": 100, "min_elevation_deg": 10}


def states():
    position, normal = ground_state(SITE, EPOCH)
    samples = []
    for second in range(0, 601, 30):
        for node, radius in (("sat004", 6921000), ("RELAY-A", 42164000)):
            samples.append({"node_id": node, "timestamp_ms": EPOCH + second * 1000,
                            "position_eci_m": [radius * v for v in normal]})
    return {"samples": samples, "events": []}


class DynamicMissionTests(unittest.TestCase):
    def test_wgs84_and_rotating_ground_normal(self):
        site = {**SITE, "altitude_m": 0}
        position, normal = ground_state(site, EPOCH)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in position)), 6378137)
        quarter, _ = ground_state(site, EPOCH + 86164.0905 * 250)
        self.assertAlmostEqual(sum(a * b for a, b in zip(position, quarter)) / 6378137 ** 2, 0, places=6)
        polar, _ = ground_state({**site, "latitude_deg": 90}, EPOCH)
        self.assertAlmostEqual(polar[2], 6356752.314245, places=5)
        self.assertTrue(above_mask(site, EPOCH, tuple(v * 7000000 for v in normal)))
        self.assertFalse(above_mask(site, EPOCH, tuple(-v * 7000000 for v in normal)))

    def test_dynamic_windows_are_bounded_and_role_aware(self):
        communication, data, metadata = dynamic_network(horizon_s=600, step_s=30,
            sites={"ground:MISSION-CONTROL": SITE}, ephemeris=states())
        self.assertEqual(metadata["source"], "provided ephemeris")
        self.assertTrue(communication.network.contacts)
        self.assertTrue(all(0 <= c.start_s < c.end_s <= 600 for c in communication.network.contacts))
        kinds = {c.kind.value for c in communication.network.contacts}
        self.assertTrue({"comm-ground", "compute-ground", "compute-comm"}.issubset(kinds))
        self.assertEqual(communication.relay_ids, ["comm:RELAY-A"])
        self.assertIn("ground_stations", data)
        self.assertTrue(any(c.start_s == 0 and c.end_s == 600 for c in communication.network.contacts))

    def test_no_ground_link_below_mask_or_through_earth(self):
        blocked = states()
        for sample in blocked["samples"]:
            sample["position_eci_m"] = [-v for v in sample["position_eci_m"]]
        communication, _, _ = dynamic_network(horizon_s=600, step_s=30,
            sites={"ground:MISSION-CONTROL": SITE}, ephemeris=blocked)
        self.assertFalse(any("ground:" in c.source or "ground:" in c.destination for c in communication.network.contacts))

    def test_no_silent_gmat_fallback(self):
        with patch("oslurm.network.dynamic.detect_backend") as detect:
            detect.return_value.real = False
            with self.assertRaisesRegex(RuntimeError, "real GMAT required"):
                dynamic_network(horizon_s=600, step_s=30, sites={"ground:MISSION-CONTROL": SITE})

    def test_bad_or_truncated_ephemeris_is_rejected(self):
        for data in ({"samples": [], "events": []},
                     {"samples": states()["samples"][:-2], "events": []},
                     {"samples": states()["samples"] + states()["samples"][:1], "events": []}):
            with self.assertRaises(ValueError):
                dynamic_network(horizon_s=600, step_s=30, sites={"ground:MISSION-CONTROL": SITE}, ephemeris=data)
        with self.assertRaises(ValueError):
            with_ground_sites(states(), {"sat004": SITE})

    def test_end_to_end_dynamic_profile_has_no_double_counting(self):
        runtime = MultiConstellationRuntime(Path.cwd())
        runtime.load_constellation("compute", "configs/compute-ai.yaml")
        runtime.load_constellation("comm", "configs/relay-public.yaml")
        runtime.connect("compute-ai", "relay-public")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_joint_axb(root, dimension=128, deadline_s=600, runtime=runtime,
                ephemeris=states(), ground_stations=str(Path.cwd() / "configs/ground-stations.json"), run_id="dynamic-test",
                contact_step_s=30, transport="local")
            self.assertEqual(result["status"], "completed", result)
            path = root / "profiles/dynamic-test"
            report = json.loads((path / "mission-profile.json").read_text())
            mission = report["jobs"][0]
            self.assertAlmostEqual(mission["mission_latency_s"], mission["accounted_latency_s"], places=7)
            self.assertAlmostEqual(mission["unattributed_s"], 0, places=7)
            for stage in (mission["input"], mission["result"]):
                self.assertAlmostEqual(stage["elapsed_s"], stage["window_wait_s"] + stage["link_occupied_s"])
                self.assertAlmostEqual(stage["link_occupied_s"], stage["serialization_s"] + stage["acquisition_s"] + stage["propagation_s"])
            self.assertTrue((path / "gmat-events.json").is_file())
            self.assertTrue((path / "contacts.json").is_file())
            metrics = json.loads((path / "metrics.json").read_text())
            self.assertEqual(metrics["trace_bytes_written"], (path / "events.jsonl").stat().st_size)
            perfetto = json.loads((path / "perfetto.json").read_text())["traceEvents"]
            spans = [e for e in perfetto if e["name"] == "COMPUTE_COMPLETED"]
            self.assertEqual(spans[0]["ph"], "X")
            self.assertAlmostEqual(spans[0]["ts"] / 1e6, runtime.last_decision.compute_start_s)
            self.assertEqual(len(ProfileAnalyzer(path).mission_metrics("JOINT-AXB001")["jobs"]), 1)
            ProfileAnalyzer(path).export_perfetto(path / "wall.json", time_axis="wall")
            wall = json.loads((path / "wall.json").read_text())["traceEvents"]
            self.assertTrue(all(e["ph"] == "i" for e in wall if e["name"] == "TRANSFER_COMPLETED"))
            self.assertEqual(next(e for e in wall if e["name"] == "COMPUTE_COMPLETED")["ph"], "X")


if __name__ == "__main__":
    unittest.main()

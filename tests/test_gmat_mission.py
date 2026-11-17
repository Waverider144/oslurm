import math
import unittest
from pathlib import Path
from unittest.mock import patch

from providers.gmat.backend import detect_backend
from providers.gmat.mission import fixed_site, mission_script, real_mission_ephemeris
from oslurm.network.dynamic import dynamic_network
from oslurm.network.ground import ground_state


SITE = {"latitude_deg": 0, "longitude_deg": 0, "altitude_m": 100, "min_elevation_deg": 10}


class GmatMissionTests(unittest.TestCase):
    def test_mission_force_model_and_native_coordinates(self):
        script = mission_script(Path("states.csv"), {"ground:MISSION-CONTROL": SITE}, 10, 1)
        self.assertIn("Degree = 8", script)
        self.assertIn("FM.PointMasses = {Sun, Luna}", script)
        self.assertIn("Prop.Accuracy = 1e-12", script)
        self.assertIn("sat004.EarthFixed.X", script)
        self.assertEqual(script.count("GroundProxy0.A1ModJulian = sat001.A1ModJulian"), 2)
        self.assertIn("GroundProxy0.EarthMJ2000Eq.X", script)
        with self.assertRaises(ValueError):
            fixed_site({**SITE, "min_elevation_deg": float("nan")})

    def test_real_native_conversion_and_step_convergence(self):
        backend = detect_backend()
        if not backend.real:
            self.skipTest("real GMAT installation required")
        sites = {"ground:MISSION-CONTROL": SITE}
        fine = real_mission_ephemeris(backend.executable, sites, 10, 1)
        coarse = real_mission_ephemeris(backend.executable, sites, 10, 5)
        for sample in fine["samples"]:
            a = math.sqrt(sum(v*v for v in sample["position_fixed_m"]))
            b = math.sqrt(sum(v*v for v in sample["position_eci_m"]))
            self.assertAlmostEqual(a, b, places=4)
        for index, frame in enumerate(fine["frames"]):
            sample = fine["samples"][index*6]
            transformed = [sum(a*b for a,b in zip(row, sample["position_fixed_m"])) for row in frame["fixed_to_eci"]]
            self.assertLess(math.dist(transformed, sample["position_eci_m"]), .001)
            self.assertGreater(math.sqrt(sum(v*v for v in frame["sun_eci_m"])), 1e11)
        lookup = {(s["node_id"], s["timestamp_ms"]): s for s in fine["samples"]}
        for sample in coarse["samples"]:
            reference = lookup[sample["node_id"], sample["timestamp_ms"]]
            self.assertLess(math.dist(sample["position_eci_m"], reference["position_eci_m"]), .1)
        station = fine["ground_samples"][0]
        approximate, _ = ground_state(SITE, station["timestamp_ms"])
        self.assertGreater(math.dist(station["position_eci_m"], approximate), 100)
        with patch("oslurm.network.ground.ground_state", side_effect=AssertionError("GMST forbidden")):
            communication, _, metadata = dynamic_network(horizon_s=10, step_s=1, sites=sites, ephemeris=fine)
        self.assertIn("native conversion", metadata["ground_frame"])
        self.assertTrue(communication.network.contacts)


if __name__ == "__main__":
    unittest.main()

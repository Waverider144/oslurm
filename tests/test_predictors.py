import unittest

from oslurm.models import OrbitEvent, OrbitSample, WindowTerminationCause
from oslurm.power import PowerConfig, project_soc
from oslurm.thermal import ThermalConfig, project_temperature
from oslurm.topology import earth_blocks_los, link_exists
from oslurm.windows import build_resource_windows


class PredictorTests(unittest.TestCase):
    def test_energy_predictor_crosses_reserve_in_eclipse(self):
        cfg = PowerConfig(battery_capacity_wh=100, initial_soc=0.5, reserve_soc=0.3, baseline_load_w=100, comm_load_w=0, compute_load_w=100)
        result = project_soc(0.5, 720, False, cfg)
        self.assertLess(result["ending_soc"], 0.3)
        self.assertIsNotNone(result["reserve_crossing_s"])

    def test_thermal_predictor_reports_headroom(self):
        cfg = ThermalConfig(initial_temperature_c=42, soft_limit_c=70, compute_power_w=120)
        result = project_temperature(42, 180, True, cfg)
        self.assertIn("minimum_headroom_c", result)
        self.assertLess(result["predicted_peak_temp_c"], 80)

    def test_los_blocks_through_earth(self):
        self.assertTrue(earth_blocks_los((7_000_000, 0, 0), (-7_000_000, 0, 0)))

    def test_link_exists_for_near_visible_pair(self):
        a = OrbitSample("sat001", 0, (7_000_000, 0, 0), (0, 0, 0), True)
        b = OrbitSample("sat002", 0, (7_000_000, 500_000, 0), (0, 0, 0), True)
        self.assertTrue(link_exists(a, b, 1_000_000))

    def test_window_slicing_uses_orbital_event_boundaries(self):
        samples = [
            OrbitSample("sat002", 1000, (7_000_000, 0, 0), (0, 0, 0), True),
            OrbitSample("sat002", 241000, (7_000_000, 0, 0), (0, 0, 0), False),
        ]
        events = [OrbitEvent("ECLIPSE_ENTRY", "sat002", 241000)]
        windows = build_resource_windows(samples, events, 300, PowerConfig(), ThermalConfig())
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].end_ms, 241000)
        self.assertEqual(windows[0].termination_causes, [WindowTerminationCause.ECLIPSE_ENTRY])


if __name__ == "__main__":
    unittest.main()


import unittest

from oslurm.models import OrbitalJobSpec, PredictedResourceWindow
from oslurm.scheduler import feasible, generate_candidates, select_candidate


def window(node: str, soc: float, peak: float, end: int = 300_000) -> PredictedResourceWindow:
    return PredictedResourceWindow(
        window_id=node,
        node_id=node,
        start_ms=0,
        end_ms=end,
        predicted_at_ms=0,
        confidence=0.9,
        compute={"cpus_free": 4, "ram_mb_free": 1024},
        energy={"ending_soc": soc, "safe_compute_energy_wh": (soc - 0.35) * 500},
        thermal={"predicted_peak_temp_c": peak},
        connectivity={"connected": True, "stable": True},
        reliability={"survival_probability": 0.98},
        termination_causes=[],
    )


class SchedulerTests(unittest.TestCase):
    def test_feasible_rejects_low_soc(self):
        job = OrbitalJobSpec("42", 0, 180, 600, 1, 128, 0.35, 72)
        self.assertFalse(feasible(job, window("sat002", 0.31, 60)))

    def test_feasible_accepts_good_window(self):
        job = OrbitalJobSpec("42", 0, 180, 600, 1, 128, 0.35, 72)
        self.assertTrue(feasible(job, window("sat004", 0.52, 58)))

    def test_select_candidate_prefers_energy_margin(self):
        job = OrbitalJobSpec("42", 0, 180, 600, 1, 128, 0.35, 72)
        candidates = generate_candidates(job, [window("sat001", 0.45, 60), window("sat004", 0.65, 60)])
        self.assertEqual(candidates[0].nodes, ["sat004"])
        self.assertEqual(select_candidate(job, [window("sat001", 0.45, 60), window("sat004", 0.65, 60)]).nodes, ["sat004"])

    def test_runtime_must_fit_window(self):
        job = OrbitalJobSpec("42", 0, 180, 600, 1, 128, 0.35, 72)
        self.assertFalse(feasible(job, window("sat001", 0.8, 60, end=60_000)))


if __name__ == "__main__":
    unittest.main()


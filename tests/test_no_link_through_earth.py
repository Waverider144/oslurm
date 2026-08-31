import unittest

from oslurm.network.models import ContactWindow
from oslurm.network.runtime import MultiConstellationRuntime
from oslurm.network.service import NetworkPlanningService
from oslurm.visibility.models import VisibilityResult, VisibilityRejectionReason


class NoLinkThroughEarthTests(unittest.TestCase):
    def test_no_link_through_earth_for_compute_comm_and_access(self):
        runtime = MultiConstellationRuntime(__import__("pathlib").Path.cwd())
        for source, destination in [
            ("compute/SAT-A", "compute/SAT-C"),
            ("comm/R1", "comm/R4"),
            ("compute/SAT-A", "comm/R3"),
        ]:
            result = runtime.visibility.visibility_check if False else runtime.visibility.evaluate(runtime._visibility_query(source.replace("/", ":"), destination.replace("/", ":")))
            self.assertFalse(result.geometrically_visible, (source, destination, result))
            self.assertEqual(result.reason, VisibilityRejectionReason.EARTH_OCCULTATION)

    def test_network_service_rejects_invisible_contact_guard(self):
        service = NetworkPlanningService()
        invisible = VisibilityResult(False, True, "Earth", True, True, None, None, -10.0, VisibilityRejectionReason.EARTH_OCCULTATION, 0.95)
        with self.assertRaises(ValueError):
            service.add_contacts([ContactWindow("bad", "A", "B", 0, 10, 1, 1, visibility=invisible)])


if __name__ == "__main__":
    unittest.main()

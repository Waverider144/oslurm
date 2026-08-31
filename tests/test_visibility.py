import math
import unittest

from oslurm.visibility import AnalyticEllipsoidVisibilityProvider, AnalyticSphereVisibilityProvider, BodyEllipsoid, TerminalFov, VisibilityQuery, VisibilityWindowQuery
from oslurm.visibility.models import VisibilityRejectionReason


R = 6_371_000.0
IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class VisibilityTests(unittest.TestCase):
    def test_ellipsoid_fidelity_uses_polar_radius(self):
        body = BodyEllipsoid(equatorial_radius_m=R, polar_radius_m=R - 100_000, safety_clearance_m=0)
        ellipsoid = AnalyticEllipsoidVisibilityProvider(body=body)
        sphere = AnalyticSphereVisibilityProvider(earth_radius_m=R, safety_clearance_m=0)
        source = (0.0, -1_000_000.0, R - 50_000.0)
        destination = (0.0, 1_000_000.0, R - 50_000.0)
        ellipsoid_result = ellipsoid.evaluate(VisibilityQuery("A", "B", source_position_eci_m=source, destination_position_eci_m=destination))
        sphere_result = sphere.evaluate(VisibilityQuery("A", "B", source_position_eci_m=source, destination_position_eci_m=destination))
        self.assertTrue(ellipsoid_result.geometrically_visible)
        self.assertEqual(ellipsoid_result.fidelity, "ellipsoid:wgs84")
        self.assertFalse(sphere_result.geometrically_visible)

    def test_clear_and_earth_blocked_los(self):
        provider = AnalyticSphereVisibilityProvider(safety_clearance_m=0)
        clear = provider.evaluate(VisibilityQuery(
            "compute:SAT-A",
            "compute:SAT-B",
            source_position_eci_m=(R + 700_000, 0, 0),
            destination_position_eci_m=(R + 700_000, 400_000, 0),
        ))
        blocked = provider.evaluate(VisibilityQuery(
            "compute:SAT-A",
            "compute:SAT-C",
            source_position_eci_m=(R + 700_000, 0, 0),
            destination_position_eci_m=(-(R + 700_000), 0, 0),
        ))
        self.assertTrue(clear.geometrically_visible)
        self.assertFalse(blocked.geometrically_visible)
        self.assertEqual(blocked.reason, VisibilityRejectionReason.EARTH_OCCULTATION)
        self.assertLess(blocked.limb_clearance_m, 0)

    def test_source_and_destination_fov_fail_closed(self):
        provider = AnalyticSphereVisibilityProvider(safety_clearance_m=0, strict=True)
        away = TerminalFov("away", boresight_body=(-1, 0, 0), cone_half_angle_rad=math.radians(20), require_pointing=True, body_to_inertial=IDENTITY)
        source_reject = provider.evaluate(VisibilityQuery(
            "compute:SAT-A",
            "compute:SAT-D",
            source_position_eci_m=(R + 700_000, 0, 0),
            destination_position_eci_m=(R + 700_000, 400_000, 0),
            require_source_fov=True,
            source_terminal=away,
        ))
        unknown = provider.evaluate(VisibilityQuery(
            "compute:SAT-A",
            "compute:SAT-D",
            source_position_eci_m=(R + 700_000, 0, 0),
            destination_position_eci_m=(R + 700_000, 400_000, 0),
            require_destination_fov=True,
        ))
        self.assertEqual(source_reject.reason, VisibilityRejectionReason.SOURCE_FOV_VIOLATION)
        self.assertEqual(unknown.reason, VisibilityRejectionReason.DESTINATION_POINTING_UNAVAILABLE)

    def test_ground_horizon(self):
        provider = AnalyticSphereVisibilityProvider(safety_clearance_m=0)
        above = provider.evaluate(VisibilityQuery("ground:GS1", "compute:SAT-A", source_position_eci_m=(R, 0, 0), destination_position_eci_m=(R + 700_000, 0, 0)))
        below = provider.evaluate(VisibilityQuery("ground:GS1", "compute:SAT-C", source_position_eci_m=(R, 0, 0), destination_position_eci_m=(-(R + 700_000), 0, 0)))
        self.assertTrue(above.geometrically_visible)
        self.assertFalse(below.geometrically_visible)

    def test_contact_window_splits_on_visibility_transition(self):
        provider = AnalyticSphereVisibilityProvider(safety_clearance_m=0)
        samples = (
            (0.0, VisibilityQuery("A", "B", source_position_eci_m=(R + 700_000, 0, 0), destination_position_eci_m=(R + 700_000, 500_000, 0))),
            (10.0, VisibilityQuery("A", "C", source_position_eci_m=(R + 700_000, 0, 0), destination_position_eci_m=(-(R + 700_000), 0, 0))),
            (20.0, VisibilityQuery("A", "B", source_position_eci_m=(R + 700_000, 0, 0), destination_position_eci_m=(R + 700_000, 500_000, 0))),
        )
        windows = provider.windows(VisibilityWindowQuery(samples=samples, tolerance_s=0.5))
        self.assertEqual([w.result.geometrically_visible for w in windows], [True, False, True])
        self.assertLessEqual(windows[0].end_s, 10.0)
        self.assertGreaterEqual(windows[1].end_s, windows[1].start_s)


if __name__ == "__main__":
    unittest.main()

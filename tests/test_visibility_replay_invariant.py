import tempfile
import unittest
from pathlib import Path

from oslurm.profile.analysis import ProfileAnalyzer
from oslurm.profile.recorder import FlightRecorder
from oslurm.profile.schema import TraceEventType


class VisibilityReplayInvariantTests(unittest.TestCase):
    def test_link_active_during_occultation_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = FlightRecorder("visibility-invariant", root=root)
            recorder.emit(TraceEventType.EARTH_OCCULTATION_BEGIN, 10, node_id="A", payload={"source": "A", "destination": "B"})
            recorder.emit(TraceEventType.LINK_ACTIVE, 20, node_id="A", payload={"source": "A", "destination": "B"})
            recorder.close()
            analyzer = ProfileAnalyzer(root / "profiles" / "visibility-invariant")
            self.assertEqual(len(analyzer.visibility_invariant_violations()), 1)


if __name__ == "__main__":
    unittest.main()

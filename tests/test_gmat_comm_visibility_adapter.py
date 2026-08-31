import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


R = 6_371_000.0


def load_adapter():
    path = Path.cwd() / "gmat-comm" / "adapters" / "gmat" / "gmat_comm_ephemeris.py"
    spec = importlib.util.spec_from_file_location("gmat_comm_ephemeris", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class GmatCommVisibilityAdapterTests(unittest.TestCase):
    def test_adapter_does_not_emit_earth_blocked_contacts_and_slices_windows(self):
        adapter = load_adapter()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "gmat-events.json"
            output_path = root / "contacts.json"
            samples = [
                {"node_id": "sat-a", "timestamp_ms": 0, "position_eci_m": [R + 700000, 0, 0], "velocity_eci_mps": [0, 0, 0]},
                {"node_id": "sat-b", "timestamp_ms": 0, "position_eci_m": [R + 700000, 500000, 0], "velocity_eci_mps": [0, 0, 0]},
                {"node_id": "sat-a", "timestamp_ms": 60000, "position_eci_m": [R + 700000, 0, 0], "velocity_eci_mps": [0, 0, 0]},
                {"node_id": "sat-b", "timestamp_ms": 60000, "position_eci_m": [-(R + 700000), 0, 0], "velocity_eci_mps": [0, 0, 0]},
                {"node_id": "sat-a", "timestamp_ms": 120000, "position_eci_m": [R + 700000, 0, 0], "velocity_eci_mps": [0, 0, 0]},
                {"node_id": "sat-b", "timestamp_ms": 120000, "position_eci_m": [R + 700000, 500000, 0], "velocity_eci_mps": [0, 0, 0]},
            ]
            input_path.write_text(json.dumps({"samples": samples}), encoding="utf-8")
            result = adapter.convert(input_path, output_path, 20_000_000.0)
            self.assertEqual(len(result["contacts"]), 2)
            self.assertEqual(result["metrics"]["earth_occultation_rejected"], 1)
            self.assertTrue(all(c["visibility"]["geometrically_visible"] for c in result["contacts"]))


if __name__ == "__main__":
    unittest.main()

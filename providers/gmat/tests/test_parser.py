import json
import tempfile
import unittest
from pathlib import Path

from providers.gmat.parser import parse_json


class ParserTests(unittest.TestCase):
    def test_parse_standard_json(self):
        payload = {
            "samples": [
                {
                    "node_id": "sat001",
                    "timestamp_ms": 1,
                    "position_eci_m": [1, 2, 3],
                    "velocity_eci_mps": [4, 5, 6],
                    "in_sunlight": True,
                }
            ],
            "events": [{"type": "ECLIPSE_ENTRY", "node_id": "sat001", "timestamp_ms": 2}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            samples, events = parse_json(path)
        self.assertEqual(samples[0].node_id, "sat001")
        self.assertEqual(events[0].type, "ECLIPSE_ENTRY")


if __name__ == "__main__":
    unittest.main()


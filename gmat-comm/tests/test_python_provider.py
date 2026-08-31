import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers.python.gmat_comm_provider import CommunicationQuery, FileCommunicationEnvelopeProvider


class PythonProviderTests(unittest.TestCase):
    def test_file_provider_interpolates_and_rejects_extrapolation(self):
        provider = FileCommunicationEnvelopeProvider(str(Path(__file__).resolve().parents[1] / "measured/example_terminal/manifest.yaml"))
        mid = provider.bandwidth(CommunicationQuery(range_m=1_000_000))
        self.assertGreater(mid.nominal, 1_200_000_000)
        outside = provider.bandwidth(CommunicationQuery(range_m=10_000_000))
        self.assertTrue(outside.extrapolated)
        self.assertEqual(outside.nominal, 0.0)


if __name__ == "__main__":
    unittest.main()

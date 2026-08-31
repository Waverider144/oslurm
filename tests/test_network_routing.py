import unittest

from oslurm.network.models import BufferState, ContactWindow, TransferIntent
from oslurm.network.routing import continuous_plans, temporal_plans


class NetworkRoutingTests(unittest.TestCase):
    def test_continuous_and_temporal_routes(self):
        intent = TransferIntent("X1", "A", "C", 1000, 0, 100)
        direct = ContactWindow("D", "A", "C", 10, 60, 8000, 100000)
        first = ContactWindow("A-B", "A", "B", 0, 20, 8000, 100000)
        second = ContactWindow("B-C", "B", "C", 25, 80, 8000, 100000)
        self.assertEqual(continuous_plans(intent, [direct])[0].hops[0].contact_id, "D")
        temporal = temporal_plans(intent, [first, second], {"B": BufferState(100000)})
        self.assertEqual(len(temporal[0].hops), 2)

    def test_buffer_capacity_blocks_store_carry_forward(self):
        intent = TransferIntent("X1", "A", "C", 1000, 0, 100)
        first = ContactWindow("A-B", "A", "B", 0, 20, 8000, 100000)
        second = ContactWindow("B-C", "B", "C", 25, 80, 8000, 100000)
        self.assertEqual(temporal_plans(intent, [first, second], {"B": BufferState(100)}), [])


if __name__ == "__main__":
    unittest.main()

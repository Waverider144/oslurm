from __future__ import annotations

from dataclasses import dataclass, field

from oslurm.models import NodeId, TimestampMs


@dataclass
class NeighborSchedulingTable:
    _advertisements: dict[NodeId, object] = field(default_factory=dict)
    stale_rejected: int = 0

    def update(self, advertisement: object) -> bool:
        node_id = getattr(advertisement, "node_id")
        sequence = getattr(advertisement, "sequence")
        existing = self._advertisements.get(node_id)
        if existing is not None and sequence <= getattr(existing, "sequence"):
            self.stale_rejected += 1
            return False
        self._advertisements[node_id] = advertisement
        return True

    def reachable(self, now: TimestampMs, reachable_nodes: set[NodeId] | None = None) -> list[object]:
        ads = []
        for node_id, ad in self._advertisements.items():
            if reachable_nodes is not None and node_id not in reachable_nodes:
                continue
            if getattr(ad, "valid_until") >= now:
                ads.append(ad)
        return sorted(ads, key=lambda a: getattr(a, "node_id"))

    def get(self, node_id: NodeId) -> object | None:
        return self._advertisements.get(node_id)

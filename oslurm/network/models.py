from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..visibility.models import VisibilityResult


class NetworkDomain(str, Enum):
    COMPUTE = "compute"
    COMM = "comm"
    ACCESS = "access"
    GROUND = "ground"


@dataclass(frozen=True, order=True)
class NetworkNodeId:
    domain: NetworkDomain
    name: str

    @classmethod
    def parse(cls, value: str) -> "NetworkNodeId":
        if ":" in value:
            domain, name = value.split(":", 1)
            return cls(NetworkDomain(domain), name)
        lowered = value.lower()
        if lowered.startswith("relay"):
            return cls(NetworkDomain.COMM, value)
        if lowered.startswith("ground"):
            return cls(NetworkDomain.GROUND, value)
        return cls(NetworkDomain.COMPUTE, value)

    def __str__(self) -> str:
        return f"{self.domain.value}:{self.name}"


class LinkKind(str, Enum):
    COMPUTE_TO_COMPUTE = "compute-compute"
    COMPUTE_TO_COMM = "compute-comm"
    COMM_TO_COMM = "comm-comm"
    COMM_TO_GROUND = "comm-ground"
    COMPUTE_TO_GROUND = "compute-ground"
    ACCESS = "access"


class DeliverySemantics(str, Enum):
    BEST_EFFORT = "best-effort"
    DEADLINE_BOUND = "deadline-bound"
    RELIABLE = "reliable"
    CUSTODY_TRANSFER = "custody-transfer"


class TransferPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TransportPathKind(str, Enum):
    CONTINUOUS = "continuous"
    TEMPORAL_STORE_CARRY_FORWARD = "temporal-store-carry-forward"


class NetworkReservationState(str, Enum):
    ACCEPTED = "accepted"
    COMMITTED = "committed"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ABORTED = "aborted"


@dataclass
class BufferState:
    capacity_bytes: int
    used_bytes: int = 0
    reserved_bytes: int = 0

    @property
    def available_bytes(self) -> int:
        return max(0, self.capacity_bytes - self.used_bytes - self.reserved_bytes)


@dataclass(frozen=True)
class ContactWindow:
    contact_id: str
    source: str
    destination: str
    start_s: float
    end_s: float
    bandwidth_bps: int
    conservative_transfer_bytes: int
    latency_ms: float = 0.0
    survival_probability: float = 1.0
    confidence: float = 1.0
    kind: LinkKind = LinkKind.COMM_TO_COMM
    source_terminal: str = "tx0"
    destination_terminal: str = "rx0"
    visibility: VisibilityResult | None = None

    def capacity_for(self, start_s: float) -> int:
        usable_s = max(0.0, self.end_s - max(self.start_s, start_s))
        return min(self.conservative_transfer_bytes, int(usable_s * self.bandwidth_bps / 8.0))


@dataclass(frozen=True)
class TransferIntent:
    transfer_id: str
    source: str
    destination: str
    bytes: int
    earliest_start_s: float = 0.0
    deadline_s: float | None = None
    priority: TransferPriority = TransferPriority.NORMAL
    delivery: DeliverySemantics = DeliverySemantics.BEST_EFFORT
    job_id: str | None = None


@dataclass(frozen=True)
class TransferHop:
    source: str
    destination: str
    contact_id: str
    start_s: float
    end_s: float
    reserved_bytes: int
    bandwidth_bps: int


@dataclass
class TransferPlan:
    transfer_id: str
    path_kind: TransportPathKind
    hops: list[TransferHop]
    predicted_finish_s: float
    bottleneck_bandwidth_bps: int
    survival_probability: float = 1.0
    confidence: float = 1.0
    selected_for_compute_node: str | None = None
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "path_kind": self.path_kind.value,
            "hops": [hop.__dict__ for hop in self.hops],
            "predicted_finish_s": self.predicted_finish_s,
            "bottleneck_bandwidth_bps": self.bottleneck_bandwidth_bps,
            "survival_probability": self.survival_probability,
            "confidence": self.confidence,
            "selected_for_compute_node": self.selected_for_compute_node,
            "rationale": self.rationale,
        }


@dataclass
class NetworkReservation:
    reservation_id: str
    transfer_id: str
    hop: TransferHop
    state: NetworkReservationState
    created_at_s: float
    expires_at_s: float
    lease_s: float = 30.0


@dataclass
class CommunicationAccessState:
    node_id: str
    neighbors: list[str] = field(default_factory=list)
    terminal_capacity: int = 1
    active_reservations: int = 0
    buffer: BufferState = field(default_factory=lambda: BufferState(0))


@dataclass
class Constellation:
    constellation_id: str
    domain: NetworkDomain
    nodes: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

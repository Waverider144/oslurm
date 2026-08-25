from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from oslurm.models import JobId, NodeId, TimestampMs


ReservationId = str


class ReservationState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    COMMITTED = "COMMITTED"
    EXPIRED = "EXPIRED"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class ResourceEnvelope:
    cpus: int
    ram_mb: int
    compute_units_per_s: float
    minimum_soc: float
    thermal_headroom_c: float


@dataclass
class ResourceReservation:
    reservation_id: ReservationId
    job_id: JobId
    source: NodeId
    reserved_resources: ResourceEnvelope
    created_at: TimestampMs
    expires_at: TimestampMs
    state: ReservationState

    def expire_if_needed(self, now: TimestampMs) -> bool:
        if self.state == ReservationState.ACCEPTED and now > self.expires_at:
            self.state = ReservationState.EXPIRED
            return True
        return False

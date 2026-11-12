from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from oslurm.models import JobId, OrbitalJobSpec, OrbitalNodeState, PredictedResourceWindow, TimestampMs

from .authority import MissionPolicy, SchedulingIntent
from .neighbor_table import NeighborSchedulingTable
from .reservations import ResourceReservation


class ConnectivityMode(str, Enum):
    FULLY_CONNECTED = "FULLY_CONNECTED"
    GROUND_DISCONNECTED = "GROUND_DISCONNECTED"
    CONSTELLATION_PARTITIONED = "CONSTELLATION_PARTITIONED"
    ISOLATED = "ISOLATED"


@dataclass(frozen=True)
class RunningJob:
    job: OrbitalJobSpec
    intent: SchedulingIntent
    started_at: TimestampMs
    remaining_runtime_s: float
    progress: float = 0.0


@dataclass(frozen=True)
class PendingJob:
    job: OrbitalJobSpec
    intent: SchedulingIntent


@dataclass(frozen=True)
class LocalSchedulingContext:
    now: TimestampMs
    self_state: OrbitalNodeState
    own_windows: list[PredictedResourceWindow]
    neighbors: NeighborSchedulingTable
    running_jobs: list[RunningJob] = field(default_factory=list)
    pending_jobs: list[PendingJob] = field(default_factory=list)
    reservations: list[ResourceReservation] = field(default_factory=list)
    connectivity: ConnectivityMode = ConnectivityMode.FULLY_CONNECTED
    mission_policy: MissionPolicy = field(default_factory=lambda: MissionPolicy(hardware_thermal_hard_limit_c=80.0))
    peer_delivery_s: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionMetrics:
    job_completion_rate: float = 0.0
    deadline_success_rate: float = 0.0
    local_execution_count: int = 0
    remote_handoff_count: int = 0
    checkpoint_count: int = 0
    migration_count: int = 0
    ground_dependent_decisions: int = 0
    autonomous_decisions: int = 0
    advertisement_bytes: int = 0
    scheduling_protocol_bytes: int = 0
    reservation_success: int = 0
    reservation_expiry: int = 0
    stale_advertisements_rejected: int = 0
    energy_reserve_violations: int = 0
    thermal_hard_limit_violations: int = 0
    unplanned_job_loss: int = 0
    decision_latency_ms: float = 0.0


@dataclass(frozen=True)
class CentralizedBaseline:
    ground_dependent_decisions: int
    completed_jobs: tuple[JobId, ...]
    migrations: int

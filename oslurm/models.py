from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


NodeId = str
JobId = str
TimestampMs = int


@dataclass(frozen=True)
class OrbitState:
    position_eci_m: tuple[float, float, float]
    velocity_eci_mps: tuple[float, float, float]
    in_sunlight: bool


@dataclass(frozen=True)
class ComputeState:
    cpus_total: int
    cpus_free: int
    ram_mb_total: int
    ram_mb_free: int
    accelerators: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EnergyState:
    battery_capacity_wh: float
    soc: float
    reserve_soc: float


@dataclass(frozen=True)
class ThermalState:
    temperature_c: float
    soft_limit_c: float
    hard_limit_c: float


@dataclass(frozen=True)
class LinkState:
    target: NodeId
    bandwidth_bps: int
    latency_ms: float


@dataclass(frozen=True)
class OrbitalNodeState:
    node_id: NodeId
    observed_at_ms: TimestampMs
    orbit: OrbitState
    compute: ComputeState
    energy: EnergyState
    thermal: ThermalState
    links: list[LinkState]
    storage: dict[str, Any]
    health: dict[str, Any]
    failure_domains: dict[str, str]
    scheduler: dict[str, Any]
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OrbitalJobSpec:
    job_id: JobId
    submitted_at_ms: TimestampMs
    runtime_s: float
    deadline_s: float
    cpus: int
    ram_mb: int
    min_soc: float
    max_temp_c: float
    replicas: int = 1
    checkpoint_supported: bool = True
    required_connectivity: str | None = None
    anti_affinity_domain: str | None = None
    labels: dict[str, str] = field(default_factory=dict)


class WindowTerminationCause(str, Enum):
    ECLIPSE_ENTRY = "ECLIPSE_ENTRY"
    ECLIPSE_EXIT = "ECLIPSE_EXIT"
    ISL_ACQUIRE = "ISL_ACQUIRE"
    ISL_LOSS = "ISL_LOSS"
    ENERGY_RESERVE_CROSSING = "ENERGY_RESERVE_CROSSING"
    THERMAL_LIMIT_CROSSING = "THERMAL_LIMIT_CROSSING"
    HORIZON = "HORIZON"


@dataclass(frozen=True)
class PredictedResourceWindow:
    window_id: str
    node_id: NodeId
    start_ms: TimestampMs
    end_ms: TimestampMs
    predicted_at_ms: TimestampMs
    confidence: float
    compute: dict[str, Any]
    energy: dict[str, float]
    thermal: dict[str, float]
    connectivity: dict[str, Any]
    reliability: dict[str, float]
    termination_causes: list[WindowTerminationCause]


@dataclass(frozen=True)
class PlacementCandidate:
    job_id: JobId
    nodes: list[NodeId]
    start_ms: TimestampMs
    predicted_finish_ms: TimestampMs
    score: float
    predicted_energy_wh: float
    predicted_peak_temp_c: float
    survival_probability: float
    violated_soft_preferences: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OrbitSample:
    node_id: NodeId
    timestamp_ms: TimestampMs
    position_eci_m: tuple[float, float, float]
    velocity_eci_mps: tuple[float, float, float]
    in_sunlight: bool


@dataclass(frozen=True)
class OrbitEvent:
    type: str
    node_id: NodeId
    timestamp_ms: TimestampMs


from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from oslurm.models import JobId, TimestampMs


Priority = int


class AuthorityMode(str, Enum):
    GROUND_REQUIRED = "GROUND_REQUIRED"
    AUTONOMOUS_UNTIL = "AUTONOMOUS_UNTIL"
    FULLY_AUTONOMOUS = "FULLY_AUTONOMOUS"


@dataclass(frozen=True)
class AuthorityPolicy:
    mode: AuthorityMode
    until: TimestampMs | None = None

    @staticmethod
    def ground_required() -> "AuthorityPolicy":
        return AuthorityPolicy(AuthorityMode.GROUND_REQUIRED)

    @staticmethod
    def autonomous_until(until: TimestampMs) -> "AuthorityPolicy":
        return AuthorityPolicy(AuthorityMode.AUTONOMOUS_UNTIL, until)

    @staticmethod
    def fully_autonomous() -> "AuthorityPolicy":
        return AuthorityPolicy(AuthorityMode.FULLY_AUTONOMOUS)

    def permits_local_decision(self, now: TimestampMs, ground_connected: bool) -> bool:
        if self.mode == AuthorityMode.FULLY_AUTONOMOUS:
            return True
        if self.mode == AuthorityMode.AUTONOMOUS_UNTIL:
            return self.until is not None and now <= self.until
        return ground_connected


@dataclass(frozen=True)
class AllowedActions:
    execute_local: bool = True
    defer: bool = True
    checkpoint: bool = True
    migrate: bool = True
    replicate: bool = False
    remote_handoff: bool = True


@dataclass(frozen=True)
class ResourceConstraints:
    cpus: int
    ram_mb: int
    accelerators: dict[str, int]


@dataclass(frozen=True)
class EnergyPolicy:
    reserve_soc: float


@dataclass(frozen=True)
class ThermalPolicy:
    max_temperature_c: float


@dataclass(frozen=True)
class ResiliencePolicy:
    replicas: int = 1
    anti_affinity_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class MissionPolicy:
    hardware_thermal_hard_limit_c: float
    ground_connected: bool = True

    def effective_thermal_limit(self, requested_max_c: float) -> float:
        return min(requested_max_c, self.hardware_thermal_hard_limit_c)


@dataclass(frozen=True)
class SchedulingIntent:
    job_id: JobId
    issued_at: TimestampMs
    deadline: TimestampMs | None
    priority: Priority
    resource_constraints: ResourceConstraints
    energy_policy: EnergyPolicy
    thermal_policy: ThermalPolicy
    resilience_policy: ResiliencePolicy
    allowed_actions: AllowedActions
    authority: AuthorityPolicy
    intent_version: int


def merge_intent(current: SchedulingIntent | None, incoming: SchedulingIntent) -> SchedulingIntent:
    if current is None or incoming.intent_version > current.intent_version:
        return incoming
    return current


def with_ground_connected(policy: MissionPolicy, connected: bool) -> MissionPolicy:
    return replace(policy, ground_connected=connected)

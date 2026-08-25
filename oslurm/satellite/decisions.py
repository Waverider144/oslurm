from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from oslurm.models import JobId, NodeId, TimestampMs


RuleId = str


class SchedulingDecisionType(str, Enum):
    EXECUTE_LOCAL = "EXECUTE_LOCAL"
    OFFER_REMOTE = "OFFER_REMOTE"
    DEFER = "DEFER"
    CHECKPOINT = "CHECKPOINT"
    MIGRATE = "MIGRATE"
    REPLICATE = "REPLICATE"
    REJECT = "REJECT"


class RejectionCause(str, Enum):
    INSUFFICIENT_CPU = "INSUFFICIENT_CPU"
    INSUFFICIENT_MEMORY = "INSUFFICIENT_MEMORY"
    INSUFFICIENT_ACCELERATOR = "INSUFFICIENT_ACCELERATOR"
    DEADLINE_VIOLATION = "DEADLINE_VIOLATION"
    ENERGY_RESERVE_VIOLATION = "ENERGY_RESERVE_VIOLATION"
    THERMAL_LIMIT_VIOLATION = "THERMAL_LIMIT_VIOLATION"
    CONNECTIVITY_WINDOW_TOO_SHORT = "CONNECTIVITY_WINDOW_TOO_SHORT"
    ADVERTISEMENT_EXPIRED = "ADVERTISEMENT_EXPIRED"
    FAILURE_DOMAIN_CONFLICT = "FAILURE_DOMAIN_CONFLICT"
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"
    RESERVATION_UNAVAILABLE = "RESERVATION_UNAVAILABLE"


@dataclass(frozen=True)
class CandidateRejection:
    node_id: NodeId
    cause: RejectionCause
    observed: float | str
    required: float | str


@dataclass(frozen=True)
class DecisionMetrics:
    deadline_margin: float
    energy_margin: float
    thermal_margin: float
    connectivity_margin: float
    worst_safety_margin: float
    predicted_completion_time_s: float
    migration_cost: float
    energy_cost: float


@dataclass(frozen=True)
class TieBreaker:
    name: str
    value: str


@dataclass(frozen=True)
class DecisionReason:
    rule: RuleId
    candidates_considered: int
    rejected_candidates: list[CandidateRejection] = field(default_factory=list)
    selected_metrics: DecisionMetrics | None = None
    tie_breakers: list[TieBreaker] = field(default_factory=list)


@dataclass(frozen=True)
class SchedulingDecision:
    decision_type: SchedulingDecisionType
    job: JobId
    reason: DecisionReason
    peer: NodeId | None = None
    until: TimestampMs | None = None

    @staticmethod
    def execute_local(job: JobId, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.EXECUTE_LOCAL, job, reason)

    @staticmethod
    def offer_remote(job: JobId, peer: NodeId, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.OFFER_REMOTE, job, reason, peer=peer)

    @staticmethod
    def defer(job: JobId, until: TimestampMs, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.DEFER, job, reason, until=until)

    @staticmethod
    def checkpoint(job: JobId, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.CHECKPOINT, job, reason)

    @staticmethod
    def migrate(job: JobId, peer: NodeId, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.MIGRATE, job, reason, peer=peer)

    @staticmethod
    def reject(job: JobId, reason: DecisionReason) -> "SchedulingDecision":
        return SchedulingDecision(SchedulingDecisionType.REJECT, job, reason)

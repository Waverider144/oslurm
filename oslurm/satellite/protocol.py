from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from oslurm.models import JobId, NodeId, TimestampMs

from .reservations import ReservationId, ResourceEnvelope


OfferId = str
MessageId = str
IntentDigest = str
VisitedDomainDigest = str
QueryId = str


@dataclass(frozen=True)
class TaskSummary:
    job_id: JobId
    cpus: int
    ram_mb: int
    checkpointable: bool
    workload_class: str = "generic"


@dataclass(frozen=True)
class CheckpointDescriptor:
    checkpoint_id: str
    size_bytes: int
    progress: float


@dataclass(frozen=True)
class TaskOffer:
    message_id: MessageId
    offer_id: OfferId
    source: NodeId
    task: TaskSummary
    remaining_work_s: float
    deadline: TimestampMs | None
    checkpoint: CheckpointDescriptor | None
    required_window_ms: int
    intent_digest: IntentDigest
    created_at: TimestampMs
    expires_at: TimestampMs
    sequence: int


@dataclass(frozen=True)
class TaskAcceptance:
    message_id: MessageId
    offer_id: OfferId
    reservation_id: ReservationId
    destination: NodeId
    valid_until: TimestampMs
    earliest_start: TimestampMs
    predicted_finish: TimestampMs
    guaranteed_resource_floor: ResourceEnvelope
    sequence: int


@dataclass(frozen=True)
class TaskReject:
    message_id: MessageId
    offer_id: OfferId
    destination: NodeId
    reason: str
    sequence: int


@dataclass(frozen=True)
class TaskCommit:
    message_id: MessageId
    offer_id: OfferId
    reservation_id: ReservationId
    source: NodeId
    checkpoint: CheckpointDescriptor
    sequence: int


class TaskOfferDecisionType(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass(frozen=True)
class TaskOfferDecision:
    decision_type: TaskOfferDecisionType
    acceptance: TaskAcceptance | None = None
    rejection: TaskReject | None = None


@dataclass(frozen=True)
class ComputeQuery:
    query_id: QueryId
    origin: NodeId
    requirements: TaskSummary
    deadline: TimestampMs | None
    required_window_ms: int
    hop_budget: int
    visited_digest: VisitedDomainDigest


class ProtocolEngine:
    def __init__(self) -> None:
        self.committed_offers: set[OfferId] = set()
        self.started_tasks: set[JobId] = set()

    def commit_once(self, commit: TaskCommit) -> bool:
        if commit.offer_id in self.committed_offers:
            return False
        self.committed_offers.add(commit.offer_id)
        self.started_tasks.add(commit.checkpoint.checkpoint_id.split(":")[0])
        return True

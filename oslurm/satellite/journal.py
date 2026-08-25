from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from oslurm.models import JobId, TimestampMs


class ExecutionEvent(str, Enum):
    JOB_ACCEPTED = "JobAccepted"
    JOB_STARTED = "JobStarted"
    CHECKPOINT_CREATED = "CheckpointCreated"
    OFFER_SENT = "OfferSent"
    OFFER_ACCEPTED = "OfferAccepted"
    MIGRATION_COMMITTED = "MigrationCommitted"
    JOB_RESTORED = "JobRestored"
    JOB_COMPLETED = "JobCompleted"
    JOB_FAILED = "JobFailed"


@dataclass(frozen=True)
class ExecutionJournalEntry:
    sequence: int
    timestamp: TimestampMs
    job_id: JobId
    event: ExecutionEvent


@dataclass
class ExecutionJournal:
    entries: list[ExecutionJournalEntry] = field(default_factory=list)
    _next_sequence: int = 1

    def append(self, timestamp: TimestampMs, job_id: JobId, event: ExecutionEvent) -> ExecutionJournalEntry:
        entry = ExecutionJournalEntry(self._next_sequence, timestamp, job_id, event)
        self._next_sequence += 1
        self.entries.append(entry)
        return entry

    def sync_since(self, sequence: int = 0) -> list[ExecutionJournalEntry]:
        return [entry for entry in self.entries if entry.sequence > sequence]

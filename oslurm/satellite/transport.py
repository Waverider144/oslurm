from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class SchedulingTransport(Protocol):
    def send_advertisement(self, destination: str, advertisement: object) -> None: ...
    def send_task_offer(self, destination: str, offer: object) -> None: ...
    def send_task_accept(self, destination: str, acceptance: object) -> None: ...
    def send_task_reject(self, destination: str, rejection: object) -> None: ...
    def send_task_commit(self, destination: str, commit: object) -> None: ...


@dataclass
class SimulatedSchedulingTransport:
    messages: list[tuple[str, str, object]] = field(default_factory=list)

    def send_advertisement(self, destination: str, advertisement: object) -> None:
        self.messages.append(("ADVERTISEMENT", destination, advertisement))

    def send_task_offer(self, destination: str, offer: object) -> None:
        self.messages.append(("OFFER", destination, offer))

    def send_task_accept(self, destination: str, acceptance: object) -> None:
        self.messages.append(("ACCEPT", destination, acceptance))

    def send_task_reject(self, destination: str, rejection: object) -> None:
        self.messages.append(("REJECT", destination, rejection))

    def send_task_commit(self, destination: str, commit: object) -> None:
        self.messages.append(("COMMIT", destination, commit))

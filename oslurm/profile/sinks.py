from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .schema import TraceEvent


class TraceSink(Protocol):
    bytes_written: int

    def write_event(self, event: TraceEvent) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class JsonlTraceSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self.bytes_written = 0

    def write_event(self, event: TraceEvent) -> None:
        line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        self._fh.write(line)
        self.bytes_written += len(line.encode("utf-8"))

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self.flush()
        self._fh.close()


class InMemoryTraceSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.bytes_written = 0

    def write_event(self, event: TraceEvent) -> None:
        self.events.append(event)
        self.bytes_written += len(json.dumps(event.to_dict(), sort_keys=True).encode("utf-8")) + 1

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class OrderedJsonlTraceSink(InMemoryTraceSink):
    """Host-side offline merge for measured execution and derived model telemetry."""
    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def write_event(self, event: TraceEvent) -> None:
        self.events.append(event)
        self.bytes_written += len(json.dumps(event.to_dict(), separators=(",", ":")).encode("utf-8")) + 1

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as output:
            for event in sorted(self.events, key=lambda e: (e.header.simulation_time_ns, e.header.sequence)):
                output.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")

    def close(self) -> None:
        self.flush()

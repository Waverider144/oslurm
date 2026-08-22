from __future__ import annotations

import json
from pathlib import Path

from oslurm.models import OrbitEvent, OrbitSample


def parse_json(path: Path) -> tuple[list[OrbitSample], list[OrbitEvent]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = [
        OrbitSample(
            node_id=row["node_id"],
            timestamp_ms=int(row["timestamp_ms"]),
            position_eci_m=tuple(float(x) for x in row["position_eci_m"]),
            velocity_eci_mps=tuple(float(x) for x in row["velocity_eci_mps"]),
            in_sunlight=bool(row["in_sunlight"]),
        )
        for row in data["samples"]
    ]
    events = [OrbitEvent(type=row["type"], node_id=row["node_id"], timestamp_ms=int(row["timestamp_ms"])) for row in data["events"]]
    return samples, events


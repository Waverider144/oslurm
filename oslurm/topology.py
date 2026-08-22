from __future__ import annotations

from dataclasses import dataclass
from math import acos, sqrt

from .models import OrbitSample

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class PredictedEdge:
    source: str
    target: str
    valid_from_ms: int
    valid_until_ms: int
    min_bandwidth_bps: int
    worst_latency_ms: float
    confidence: float


def distance_m(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def earth_blocks_los(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    ax, ay, az = a
    bx, by, bz = b
    ab = (bx - ax, by - ay, bz - az)
    ab2 = sum(v * v for v in ab)
    if ab2 == 0:
        return False
    t = -sum(x * y for x, y in zip(a, ab)) / ab2
    t = max(0.0, min(1.0, t))
    closest = (ax + t * ab[0], ay + t * ab[1], az + t * ab[2])
    return sqrt(sum(v * v for v in closest)) < EARTH_RADIUS_M


def link_exists(a: OrbitSample, b: OrbitSample, max_isl_range_m: float) -> bool:
    return distance_m(a.position_eci_m, b.position_eci_m) <= max_isl_range_m and not earth_blocks_los(
        a.position_eci_m, b.position_eci_m
    )


def edges_at(samples: list[OrbitSample], max_isl_range_m: float = 4_500_000.0) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, left in enumerate(samples):
        for right in samples[i + 1 :]:
            if link_exists(left, right, max_isl_range_m):
                out.append((left.node_id, right.node_id))
    return out


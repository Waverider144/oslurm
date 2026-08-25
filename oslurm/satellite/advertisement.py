from __future__ import annotations

from dataclasses import dataclass

from oslurm.models import NodeId, OrbitalNodeState, PredictedResourceWindow, TimestampMs


@dataclass(frozen=True)
class ComputeAdvertisement:
    cpus_floor: int
    ram_mb_floor: int
    accelerators: dict[str, int]


@dataclass(frozen=True)
class EnergyAdvertisement:
    predicted_minimum_soc: float
    reserve_soc: float


@dataclass(frozen=True)
class ThermalAdvertisement:
    headroom_c: float
    hard_limit_c: float


@dataclass(frozen=True)
class FailureDomainDigest:
    domains: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SatelliteSchedulingAdvertisement:
    node_id: NodeId
    generated_at: TimestampMs
    valid_until: TimestampMs
    compute: ComputeAdvertisement
    energy: EnergyAdvertisement
    thermal: ThermalAdvertisement
    queue_delay_p50_ms: int
    queue_delay_upper_bound_ms: int
    stable_until: TimestampMs
    failure_domains: FailureDomainDigest
    sequence: int

    def usable_for_commitment(self, now: TimestampMs) -> bool:
        return now <= self.valid_until

    def compact_size_bytes(self) -> int:
        return len(repr(self).encode("utf-8"))


def generate_advertisement(
    node: OrbitalNodeState,
    window: PredictedResourceWindow,
    now: TimestampMs,
    sequence: int,
    queue_depth: int = 0,
) -> SatelliteSchedulingAdvertisement:
    stable_until = min(window.end_ms, now + 300_000)
    queue_delay_upper = queue_depth * 30_000
    predicted_peak = window.thermal.get("predicted_peak_temp_c", node.thermal.temperature_c)
    return SatelliteSchedulingAdvertisement(
        node_id=node.node_id,
        generated_at=now,
        valid_until=stable_until,
        compute=ComputeAdvertisement(
            cpus_floor=min(node.compute.cpus_free, int(window.compute.get("cpus_free", 0))),
            ram_mb_floor=min(node.compute.ram_mb_free, int(window.compute.get("ram_mb_free", 0))),
            accelerators=dict(node.compute.accelerators),
        ),
        energy=EnergyAdvertisement(
            predicted_minimum_soc=float(window.energy.get("minimum_soc", node.energy.soc)),
            reserve_soc=node.energy.reserve_soc,
        ),
        thermal=ThermalAdvertisement(
            headroom_c=max(0.0, node.thermal.hard_limit_c - predicted_peak),
            hard_limit_c=node.thermal.hard_limit_c,
        ),
        queue_delay_p50_ms=queue_depth * 10_000,
        queue_delay_upper_bound_ms=queue_delay_upper,
        stable_until=stable_until,
        failure_domains=FailureDomainDigest(tuple(sorted(node.failure_domains.items()))),
        sequence=sequence,
    )

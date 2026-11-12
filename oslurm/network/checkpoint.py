"""GMAT-Comm contact/envelope adapter for checkpoint delivery."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from .models import BufferState, ContactWindow, LinkKind, TransferIntent, TransferPlan
from .service import NetworkPlanningService


@lru_cache
def _module(name: str, relative: str):
    path = Path(__file__).resolve().parents[2] / "gmat-comm" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def deliver_file(network: NetworkPlanningService, plan: TransferPlan, source: Path,
                 destination: Path, *, now_s: float, expected_sha256: str | None = None) -> str:
    """Local verified staging, gated by a committed simulated radio delivery."""
    if now_s < plan.predicted_finish_s:
        raise ValueError("file cannot be restored before delivery")
    reservations = [r for r in network.reservations.values() if r.transfer_id == plan.transfer_id]
    if not reservations or any(r.state.value != "committed" for r in reservations):
        raise ValueError("file transfer is not committed")
    temporary = destination.with_suffix(".incoming")
    try:
        if source.stat().st_size != plan.hops[0].reserved_bytes:
            raise ValueError("file size changed after reservation")
        digest = sha256(source)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("source checksum mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, temporary)
        if sha256(temporary) != digest:
            raise ValueError("file checksum mismatch")
        temporary.replace(destination)
        network.complete_plan(plan, now_s=now_s)
    except Exception:
        network.abort_plan(plan)
        temporary.unlink(missing_ok=True)
        raise
    return digest


class CheckpointNetwork:
    def __init__(self, ephemeris: dict, *, bandwidth_cap_bps: int = 8_000_000,
                 max_range_m: float = 80_000_000, relay_buffer_bytes: int = 64_000_000):
        if bandwidth_cap_bps <= 0 or not math.isfinite(max_range_m) or max_range_m <= 0 or relay_buffer_bytes < 0:
            raise ValueError("invalid checkpoint communication limits")
        adapter = _module("oslurm_gmat_comm_geometry", "adapters/gmat/gmat_comm_ephemeris.py")
        envelopes = _module("oslurm_gmat_comm_envelopes", "providers/python/gmat_comm_provider.py")
        provider = envelopes.AnalyticCommunicationEnvelopeProvider()
        self.geometry = adapter.interval_contacts(ephemeris, max_range_m)
        self.epoch_ms = min(s["timestamp_ms"] for s in ephemeris["samples"])
        self.network = NetworkPlanningService()
        self.relay_ids = sorted({s["node_id"] for s in ephemeris["samples"]
                                 if s["node_id"].startswith(("RELAY-", "comm:"))})
        for node in self.relay_ids:
            self.network.set_buffer(node, BufferState(relay_buffer_bytes))
        for item in self.geometry["contacts"]:
            query = envelopes.CommunicationQuery(range_m=item["range_m"])
            bandwidth = min(bandwidth_cap_bps, provider.bandwidth(query).lower_bound)
            goodput = max(1, math.floor(bandwidth * (1 - provider.packet_loss(query).upper_bound)))
            acquisition = provider.acquisition_time(query).upper_bound
            latency = provider.latency(query).upper_bound
            start = (item["start_ms"] - self.epoch_ms) / 1000
            end = (item["end_ms"] - self.epoch_ms) / 1000
            capacity = max(0, math.floor((end - start - acquisition - latency) * goodput / 8))
            for source, destination in ((item["source"], item["destination"]), (item["destination"], item["source"])):
                self.network.add_contacts([ContactWindow(
                    contact_id=f"{item['contact_id']}:{source}>{destination}",
                    source=source, destination=destination, start_s=start, end_s=end,
                    bandwidth_bps=goodput, conservative_transfer_bytes=capacity,
                    latency_ms=latency * 1000, acquisition_s=acquisition,
                    survival_probability=provider.survival_probability(query).lower_bound,
                    confidence=min(provider.bandwidth(query).confidence, provider.packet_loss(query).confidence),
                    kind=self.link_kind(source, destination),
                    source_terminal="radio0", destination_terminal="radio0",
                )])

    def link_kind(self, source: str, destination: str) -> LinkKind:
        ground = source.startswith("ground:") or destination.startswith("ground:")
        relays = sum(node in self.relay_ids for node in (source, destination))
        if ground:
            return LinkKind.COMM_TO_GROUND if relays else LinkKind.COMPUTE_TO_GROUND
        return (LinkKind.COMM_TO_COMM if relays == 2 else LinkKind.COMPUTE_TO_COMM
                if relays else LinkKind.COMPUTE_TO_COMPUTE)

    def plan(self, transfer_id: str, source: str, destination: str, size: int,
             now_s: float, deadline_s: float) -> TransferPlan | None:
        plans = self.network.plan_transfer(TransferIntent(
            transfer_id=transfer_id, source=source, destination=destination, bytes=size,
            earliest_start_s=now_s, deadline_s=deadline_s, job_id="AXB001"))
        return plans[0] if plans else None

    def reserve(self, plan: TransferPlan, now_s: float):
        reservations = self.network.reserve_plan(plan, now_s=now_s)
        self.network.commit_plan(plan)
        return reservations

    def deliver(self, plan: TransferPlan, source: Path, destination: Path, *, now_s: float) -> str:
        return deliver_file(self.network, plan, source, destination, now_s=now_s)

    def export(self) -> dict:
        return {
            "provider": "GMAT-Comm analytic envelopes", "visibility_fidelity": "ellipsoid:wgs84",
            "geometry_model": self.geometry["geometry_model"],
            "contacts": [{"contact_id": c.contact_id, "source": c.source, "destination": c.destination,
                          "start_s": c.start_s, "end_s": c.end_s, "bandwidth_bps": c.bandwidth_bps,
                          "acquisition_s": c.acquisition_s, "latency_ms": c.latency_ms, "kind": c.kind.value,
                          "conservative_transfer_bytes": c.conservative_transfer_bytes}
                         for c in self.network.contacts],
            "relay_ids": self.relay_ids,
            "buffers": {node: {"capacity_bytes": b.capacity_bytes, "reserved_bytes": b.reserved_bytes,
                               "used_bytes": b.used_bytes} for node, b in self.network.buffers.items()},
            "reservations": [{"reservation_id": r.reservation_id, "transfer_id": r.transfer_id,
                              "state": r.state.value, "hop": r.hop.__dict__}
                             for r in self.network.reservations.values()],
        }

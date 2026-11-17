"""Build mission contact reservations from real GMAT states and rotating ground sites."""
from __future__ import annotations

import math
import time

from providers.gmat.adapter import real_gmat_ephemeris
from providers.gmat.backend import detect_backend
from providers.gmat.mission import real_mission_ephemeris

from .checkpoint import CheckpointNetwork
from .ground import with_ground_sites


def dynamic_network(*, horizon_s: int, step_s: int, sites: dict, bandwidth_mbps: float = 8,
                    max_range_m: float = 80000000, ephemeris: dict | None = None, fidelity: str = "mission"):
    if horizon_s <= 0 or step_s <= 0 or horizon_s % step_s or not sites:
        raise ValueError("positive divisible horizon/step and ground sites required")
    if not math.isfinite(bandwidth_mbps) or bandwidth_mbps <= 0:
        raise ValueError("positive finite bandwidth required")
    if fidelity not in {"mission", "demo"}:
        raise ValueError("unsupported propagation fidelity")
    source = "provided ephemeris"
    started = time.perf_counter()
    if ephemeris is None:
        backend = detect_backend()
        if not backend.real or not backend.executable:
            raise RuntimeError(f"real GMAT required: {backend.reason}")
        ephemeris = (real_mission_ephemeris(backend.executable, sites, horizon_s, step_s) if fidelity == "mission"
                     else real_gmat_ephemeris(backend.executable, horizon_s, step_s, include_relays=True))
        source = "real GMAT"
    propagation_wall_s = time.perf_counter() - started
    started = time.perf_counter()
    mapping = {f"sat{i:03d}": f"compute:SAT{i:03d}" for i in range(1, 5)}
    mapping.update({"RELAY-A": "comm:RELAY-A", "RELAY-B": "comm:RELAY-B"})
    samples = [{**sample, "node_id": mapping.get(sample["node_id"], sample["node_id"])}
               for sample in ephemeris["samples"]]
    if not samples:
        raise ValueError("empty ephemeris")
    times = sorted({s["timestamp_ms"] for s in samples})
    if len(times) < 2 or times[-1] - times[0] < horizon_s * 1000 - 1:
        raise ValueError("ephemeris does not cover requested horizon")
    if any(b - a > step_s * 1000 + 1 for a, b in zip(times, times[1:])):
        raise ValueError("ephemeris gaps exceed configured contact step")
    seen = set()
    for sample in samples:
        key = (sample["node_id"], sample["timestamp_ms"])
        position = sample["position_eci_m"]
        if key in seen or len(position) != 3 or not all(math.isfinite(v) for v in (*position, key[1])):
            raise ValueError("duplicate or invalid ephemeris sample")
        seen.add(key)
    if ephemeris.get("frame_model"):
        ground = ephemeris["ground_samples"]
        if any("position_fixed_m" not in sample for sample in samples + ground):
            raise ValueError("native frame ephemeris missing EarthFixed states")
        data = {**ephemeris, "samples": samples + ground, "ground_stations": sites, "geometry_frame": "EarthFixed"}
    else:
        data = with_ground_sites({"samples": samples, "events": ephemeris.get("events", [])}, sites)
    network = CheckpointNetwork(data, bandwidth_cap_bps=int(bandwidth_mbps * 1e6), max_range_m=max_range_m)
    return network, data, {"source": source, "step_s": step_s,
        "propagation_wall_s": propagation_wall_s, "window_build_wall_s": time.perf_counter() - started,
        "geometry_model": network.geometry["geometry_model"], "metrics": network.geometry["metrics"],
        "force_model": ephemeris.get("force_model", "two-body demo / provided states"),
        "shadow_model": ephemeris.get("shadow_model", "adapter cylindrical fixed +X Sun"),
        "runtime_inputs": ephemeris.get("runtime_inputs"),
        "ground_frame": ephemeris.get("frame_model", "WGS84 + approximate GMST; not full IAU/ITRF to MJ2000 transformation")}

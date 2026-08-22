from __future__ import annotations

from collections import defaultdict

from .models import OrbitEvent, OrbitSample, PredictedResourceWindow, WindowTerminationCause
from .power import PowerConfig, project_soc
from .thermal import ThermalConfig, project_temperature


def build_resource_windows(
    samples: list[OrbitSample],
    events: list[OrbitEvent],
    horizon_s: float,
    power: PowerConfig,
    thermal: ThermalConfig,
) -> list[PredictedResourceWindow]:
    by_node: dict[str, list[OrbitSample]] = defaultdict(list)
    events_by_node: dict[str, list[OrbitEvent]] = defaultdict(list)
    for sample in samples:
        by_node[sample.node_id].append(sample)
    for event in events:
        events_by_node[event.node_id].append(event)

    windows: list[PredictedResourceWindow] = []
    for node_id, node_samples in by_node.items():
        node_samples.sort(key=lambda s: s.timestamp_ms)
        t0 = node_samples[0].timestamp_ms
        horizon_ms = t0 + int(horizon_s * 1000)
        boundaries = [t0]
        boundaries += [e.timestamp_ms for e in events_by_node[node_id] if t0 < e.timestamp_ms < horizon_ms]
        boundaries.append(horizon_ms)
        boundaries = sorted(set(boundaries))
        start_soc = power.initial_soc
        start_temp = thermal.initial_temperature_c
        for idx, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            sample = max((s for s in node_samples if s.timestamp_ms <= start), key=lambda s: s.timestamp_ms)
            duration_s = (end - start) / 1000.0
            energy = project_soc(start_soc, duration_s, sample.in_sunlight, power)
            therm = project_temperature(start_temp, duration_s, sample.in_sunlight, thermal)
            causes = [
                WindowTerminationCause(e.type)
                for e in events_by_node[node_id]
                if e.timestamp_ms == end and e.type in WindowTerminationCause._value2member_map_
            ] or ([WindowTerminationCause.HORIZON] if end == horizon_ms else [])
            windows.append(
                PredictedResourceWindow(
                    window_id=f"{node_id}-{idx}",
                    node_id=node_id,
                    start_ms=start,
                    end_ms=end,
                    predicted_at_ms=t0,
                    confidence=0.85,
                    compute={"cpus_free": 4, "ram_mb_free": 8192, "accelerators": {"gpu": 0}},
                    energy={k: v for k, v in energy.items() if v is not None},
                    thermal={k: v for k, v in therm.items() if v is not None},
                    connectivity={"connected": True, "component": "demo", "stable": True},
                    reliability={"survival_probability": 0.98},
                    termination_causes=causes,
                )
            )
            start_soc = float(energy["ending_soc"])
            start_temp = float(therm["ending_temperature_c"])
    return windows


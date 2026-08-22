from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerConfig:
    battery_capacity_wh: float = 500.0
    initial_soc: float = 0.70
    reserve_soc: float = 0.30
    solar_generation_w: float = 350.0
    baseline_load_w: float = 100.0
    comm_load_w: float = 20.0
    compute_load_w: float = 80.0


def project_soc(
    start_soc: float,
    duration_s: float,
    in_sunlight: bool,
    config: PowerConfig,
    compute_active: bool = True,
) -> dict[str, float | None]:
    generation_w = config.solar_generation_w if in_sunlight else 0.0
    compute_w = config.compute_load_w if compute_active else 10.0
    load_w = config.baseline_load_w + config.comm_load_w + compute_w
    delta_wh = (generation_w - load_w) * duration_s / 3600.0
    start_wh = start_soc * config.battery_capacity_wh
    end_wh = max(0.0, min(config.battery_capacity_wh, start_wh + delta_wh))
    end_soc = end_wh / config.battery_capacity_wh
    min_soc = min(start_soc, end_soc)
    crossing_s: float | None = None
    if end_soc < config.reserve_soc and load_w > generation_w:
        reserve_wh = config.reserve_soc * config.battery_capacity_wh
        crossing_s = (start_wh - reserve_wh) / (load_w - generation_w) * 3600.0
        crossing_s = max(0.0, min(duration_s, crossing_s))
    return {
        "minimum_soc": min_soc,
        "ending_soc": end_soc,
        "safe_compute_energy_wh": max(0.0, (min_soc - config.reserve_soc) * config.battery_capacity_wh),
        "reserve_crossing_s": crossing_s,
    }


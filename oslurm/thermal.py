from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class ThermalConfig:
    initial_temperature_c: float = 42.0
    soft_limit_c: float = 70.0
    hard_limit_c: float = 80.0
    thermal_capacitance_j_per_c: float = 12000.0
    thermal_resistance_c_per_w: float = 0.20
    equilibrium_temp_sunlight_c: float = 52.0
    equilibrium_temp_eclipse_c: float = 26.0
    compute_power_w: float = 80.0


def project_temperature(
    start_temp_c: float,
    duration_s: float,
    in_sunlight: bool,
    config: ThermalConfig,
    compute_active: bool = True,
) -> dict[str, float | None]:
    env_c = config.equilibrium_temp_sunlight_c if in_sunlight else config.equilibrium_temp_eclipse_c
    power_w = config.compute_power_w if compute_active else 10.0
    equilibrium_c = env_c + power_w * config.thermal_resistance_c_per_w
    tau = config.thermal_capacitance_j_per_c * config.thermal_resistance_c_per_w
    end_temp = equilibrium_c + (start_temp_c - equilibrium_c) * exp(-duration_s / tau)
    peak = max(start_temp_c, end_temp, equilibrium_c if end_temp > start_temp_c else start_temp_c)
    minimum_headroom = config.soft_limit_c - peak
    crossing_s: float | None = None
    if start_temp_c < config.soft_limit_c and peak >= config.soft_limit_c and equilibrium_c > start_temp_c:
        ratio = (config.soft_limit_c - equilibrium_c) / (start_temp_c - equilibrium_c)
        if 0.0 < ratio < 1.0:
            crossing_s = -tau * __import__("math").log(ratio)
    return {
        "ending_temperature_c": end_temp,
        "predicted_peak_temp_c": peak,
        "minimum_headroom_c": minimum_headroom,
        "safe_additional_compute_power_w": max(0.0, minimum_headroom / config.thermal_resistance_c_per_w),
        "thermal_crossing_s": crossing_s,
    }


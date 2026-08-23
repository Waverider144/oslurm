from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvelopeValue:
    nominal: float
    lower_bound: float
    upper_bound: float
    confidence: float = 1.0
    extrapolated: bool = False


@dataclass(frozen=True)
class HardwareQuery:
    temperature_c: float
    power_cap_w: float
    clock_fraction: float
    voltage_v: float
    cumulative_dose_rad: float
    dose_rate_rad_s: float
    particle_flux: float
    workload_class: str


class HardwareEnvelopeProvider:
    def throughput(self, query: HardwareQuery) -> EnvelopeValue:
        raise NotImplementedError

    def power(self, query: HardwareQuery) -> EnvelopeValue:
        raise NotImplementedError

    def failure_rate(self, query: HardwareQuery) -> EnvelopeValue:
        raise NotImplementedError

    def memory_error_rate(self, query: HardwareQuery) -> EnvelopeValue:
        raise NotImplementedError

    def degradation(self, query: HardwareQuery) -> EnvelopeValue:
        raise NotImplementedError

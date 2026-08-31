from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvelopeValue:
    nominal: float
    lower_bound: float
    upper_bound: float
    confidence: float
    extrapolated: bool = False


@dataclass(frozen=True)
class CommunicationQuery:
    range_m: float
    relative_velocity_mps: float = 0.0
    pointing_error_rad: float = 0.0
    incidence_angle_rad: float = 0.0
    temperature_c: float = 25.0
    terminal_power_cap_w: float = 50.0
    cumulative_dose_rad: float = 0.0
    dose_rate_rad_s: float = 0.0
    optional_atmospheric_loss_db: float = 0.0
    modulation: str = "adaptive"
    coding: str = "adaptive"
    traffic_class: str = "bulk"


class CommunicationEnvelopeProvider:
    def bandwidth(self, query: CommunicationQuery) -> EnvelopeValue: ...
    def latency(self, query: CommunicationQuery) -> EnvelopeValue: ...
    def packet_loss(self, query: CommunicationQuery) -> EnvelopeValue: ...
    def acquisition_time(self, query: CommunicationQuery) -> EnvelopeValue: ...
    def survival_probability(self, query: CommunicationQuery) -> EnvelopeValue: ...
    def power(self, query: CommunicationQuery) -> EnvelopeValue: ...


class AnalyticCommunicationEnvelopeProvider:
    def bandwidth(self, query: CommunicationQuery) -> EnvelopeValue:
        nominal = max(1_000_000.0, 2_000_000_000.0 / (1.0 + query.range_m / 2_000_000.0))
        return EnvelopeValue(nominal, nominal * 0.82, nominal * 1.08, 0.8)

    def latency(self, query: CommunicationQuery) -> EnvelopeValue:
        nominal = query.range_m / 299_792_458.0
        return EnvelopeValue(nominal, nominal, nominal * 1.1, 0.95)

    def packet_loss(self, query: CommunicationQuery) -> EnvelopeValue:
        nominal = min(0.2, 0.001 + query.range_m / 1.0e10)
        return EnvelopeValue(nominal, nominal * 0.5, nominal * 1.5, 0.75)

    def acquisition_time(self, query: CommunicationQuery) -> EnvelopeValue:
        return EnvelopeValue(2.0, 1.0, 4.0, 0.8)

    def survival_probability(self, query: CommunicationQuery) -> EnvelopeValue:
        survival = max(0.5, 0.999 - query.range_m / 1.0e10)
        return EnvelopeValue(survival, max(0.0, survival - 0.02), 1.0, 0.8)

    def power(self, query: CommunicationQuery) -> EnvelopeValue:
        return EnvelopeValue(45.0, 38.0, 52.0, 0.8)


class FileCommunicationEnvelopeProvider:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.base = self.manifest_path.parent
        text = self.manifest_path.read_text(encoding="utf-8")
        self.policy = "reject" if "policy: reject" in text else "clamp"
        self.curves = {
            "bandwidth": self._read("bandwidth.csv"),
            "latency": self._read("latency.csv"),
            "packet_loss": self._read("packet_loss.csv"),
            "acquisition": self._read("acquisition.csv"),
            "power": self._read("power.csv"),
        }

    def bandwidth(self, query: CommunicationQuery) -> EnvelopeValue:
        return self._interp("bandwidth", query.range_m)

    def latency(self, query: CommunicationQuery) -> EnvelopeValue:
        return self._interp("latency", query.range_m)

    def packet_loss(self, query: CommunicationQuery) -> EnvelopeValue:
        return self._interp("packet_loss", query.range_m)

    def acquisition_time(self, query: CommunicationQuery) -> EnvelopeValue:
        return self._interp("acquisition", query.range_m)

    def survival_probability(self, query: CommunicationQuery) -> EnvelopeValue:
        loss = self.packet_loss(query)
        return EnvelopeValue(1.0 - loss.nominal, 1.0 - loss.upper_bound, 1.0 - loss.lower_bound, loss.confidence, loss.extrapolated)

    def power(self, query: CommunicationQuery) -> EnvelopeValue:
        return self._interp("power", query.range_m)

    def _read(self, file_name: str) -> list[tuple[float, EnvelopeValue]]:
        rows = []
        with (self.base / file_name).open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append((
                    float(row["range_km"]) * 1000.0,
                    EnvelopeValue(float(row["nominal"]), float(row["lower"]), float(row["upper"]), float(row["confidence"])),
                ))
        return sorted(rows, key=lambda item: item[0])

    def _interp(self, name: str, range_m: float) -> EnvelopeValue:
        rows = self.curves[name]
        if range_m < rows[0][0] or range_m > rows[-1][0]:
            if self.policy == "reject":
                return EnvelopeValue(0.0, 0.0, 0.0, 0.0, True)
            edge = rows[0][1] if range_m < rows[0][0] else rows[-1][1]
            return EnvelopeValue(edge.nominal, edge.lower_bound, edge.upper_bound, edge.confidence, True)
        for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
            if x0 <= range_m <= x1:
                t = (range_m - x0) / (x1 - x0)
                return EnvelopeValue(
                    y0.nominal + (y1.nominal - y0.nominal) * t,
                    y0.lower_bound + (y1.lower_bound - y0.lower_bound) * t,
                    y0.upper_bound + (y1.upper_bound - y0.upper_bound) * t,
                    min(y0.confidence, y1.confidence),
                )
        return rows[-1][1]

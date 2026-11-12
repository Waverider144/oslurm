"""Power/thermal digital-twin telemetry on the experiment's simulation clock."""
from __future__ import annotations

import copy
import math
from bisect import bisect_right
from dataclasses import asdict

from .power import PowerConfig, project_soc
from .thermal import ThermalConfig, project_temperature


class NodeTelemetry:
    source = "analytic_power_thermal"

    def __init__(self, ephemeris: dict, emit=None, power: PowerConfig | None = None,
                 thermal: ThermalConfig | None = None):
        self.power = power or PowerConfig()
        self.thermal = thermal or ThermalConfig()
        if not 0 <= self.power.initial_soc <= 1 or not math.isfinite(self.thermal.initial_temperature_c):
            raise ValueError("invalid initial battery/thermal state")
        self.epoch_ms = min(s["timestamp_ms"] for s in ephemeris["samples"])
        self.samples = {}
        for sample in ephemeris["samples"]:
            self.samples.setdefault((sample["timestamp_ms"] - self.epoch_ms) / 1000, {})[sample["node_id"]] = sample
        self.epochs = sorted(self.samples)
        self.nodes = sorted(self.samples[self.epochs[0]])
        self.state = {node: {"soc": self.power.initial_soc, "temperature_c": self.thermal.initial_temperature_c}
                      for node in self.nodes}
        self.now_s = 0.0
        self.emit = emit
        self.snapshot(None)

    def orbit(self, node: str, at_s: float) -> dict:
        return self.samples[self.epochs[max(0, bisect_right(self.epochs, at_s) - 1)]][node]

    def snapshot(self, active_node: str | None):
        if self.emit:
            for node, state in self.state.items():
                self.emit(self.now_s, "NODE_OPERATING_SNAPSHOT", "PAYLOAD_MODEL", node,
                          **state, telemetry_source=self.source,
                          reserve_soc=self.power.reserve_soc, soft_limit_c=self.thermal.soft_limit_c,
                          hard_limit_c=self.thermal.hard_limit_c,
                          in_sunlight=self.orbit(node, self.now_s)["in_sunlight"],
                          cpu_utilization=1.0 if node == active_node else 0.0,
                          available_cpu=1, schedulable_compute=1,
                          compute_active=node == active_node)

    def advance(self, to_s: float, active_node: str | None = None):
        if to_s < self.now_s - 1e-9:
            raise ValueError("telemetry clock cannot go backwards")
        while self.now_s < to_s - 1e-9:
            next_index = bisect_right(self.epochs, self.now_s + 1e-9)
            end = min(to_s, self.epochs[next_index] if next_index < len(self.epochs) else to_s)
            for node, state in self.state.items():
                sun = self.orbit(node, self.now_s)["in_sunlight"]
                active = node == active_node
                state["soc"] = project_soc(state["soc"], end - self.now_s, sun, self.power, active)["ending_soc"]
                state["temperature_c"] = project_temperature(state["temperature_c"], end - self.now_s, sun, self.thermal, active)["ending_temperature_c"]
            self.now_s = end
            self.snapshot(active_node)

    def preview(self):
        clone = copy.copy(self)
        clone.state = copy.deepcopy(self.state)
        clone.emit = None
        return clone

    def forecast(self, node: str, duration_s: float) -> dict:
        clone = self.preview()
        minimum = clone.state[node]["soc"]
        peak = clone.state[node]["temperature_c"]
        end_s = self.now_s + duration_s
        while clone.now_s < end_s - 1e-9:
            clone.advance(min(end_s, clone.now_s + 30), node)
            minimum = min(minimum, clone.state[node]["soc"])
            peak = max(peak, clone.state[node]["temperature_c"])
        return {"minimum_soc": minimum, "predicted_peak_temp_c": peak}

    def can_compute(self, node: str, duration_s: float) -> bool:
        forecast = self.forecast(node, duration_s)
        return forecast["minimum_soc"] >= self.power.reserve_soc and forecast["predicted_peak_temp_c"] <= self.thermal.soft_limit_c

    def metadata(self):
        return {"source": self.source, "power": asdict(self.power), "thermal": asdict(self.thermal)}

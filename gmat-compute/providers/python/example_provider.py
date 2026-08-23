from __future__ import annotations

from api.python.gmat_compute.provider import EnvelopeValue, HardwareEnvelopeProvider, HardwareQuery


class DeviceXEnvelope(HardwareEnvelopeProvider):
    def throughput(self, query: HardwareQuery) -> EnvelopeValue:
        base = 480.0 if query.workload_class == "gpu_fp16" else 100.0
        thermal = 1.0 if query.temperature_c < 75.0 else 0.75
        power = min(1.0, query.power_cap_w / 500.0)
        nominal = base * thermal * power
        return EnvelopeValue(nominal, nominal * 0.94, nominal * 1.04, 0.8, query.power_cap_w > 500.0)

    def power(self, query: HardwareQuery) -> EnvelopeValue:
        nominal = min(query.power_cap_w, 500.0)
        return EnvelopeValue(nominal, nominal * 0.98, nominal * 1.02, 0.85, query.power_cap_w > 500.0)

    def failure_rate(self, query: HardwareQuery) -> EnvelopeValue:
        nominal = 0.00001 * (1.0 + query.particle_flux / 10.0)
        return EnvelopeValue(nominal, nominal * 0.5, nominal * 2.0, 0.6, False)

    def memory_error_rate(self, query: HardwareQuery) -> EnvelopeValue:
        nominal = query.particle_flux * 1e-9
        return EnvelopeValue(nominal, nominal * 0.5, nominal * 2.0, 0.5, False)

    def degradation(self, query: HardwareQuery) -> EnvelopeValue:
        nominal = max(0.5, 1.0 - query.cumulative_dose_rad / 200000.0)
        return EnvelopeValue(nominal, nominal * 0.98, min(1.0, nominal * 1.02), 0.75, False)

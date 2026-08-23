import unittest

from api.python.gmat_compute.provider import HardwareQuery
from providers.python.example_provider import DeviceXEnvelope


class PythonProviderTests(unittest.TestCase):
    def test_provider_abi(self):
        provider = DeviceXEnvelope()
        query = HardwareQuery(
            temperature_c=25,
            power_cap_w=500,
            clock_fraction=1.0,
            voltage_v=1.0,
            cumulative_dose_rad=0,
            dose_rate_rad_s=0,
            particle_flux=0,
            workload_class="gpu_fp16",
        )
        value = provider.throughput(query)
        self.assertGreater(value.nominal, 400)
        self.assertGreater(value.upper_bound, value.lower_bound)
        self.assertFalse(value.extrapolated)


if __name__ == "__main__":
    unittest.main()

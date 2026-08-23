#pragma once

#include <cstdint>
#include <map>
#include <string>

namespace gmat_compute {

struct HardwareProfile {
    std::string id = "generic_payload";
    std::string accelerator_model = "analytic";
    double base_throughput_units_per_s = 100.0;
    double nominal_power_w = 200.0;
    double max_power_w = 500.0;
    double idle_power_w = 40.0;
    double thermal_limit_c = 80.0;
    double memory_bytes = 16.0 * 1024.0 * 1024.0 * 1024.0;
    std::map<std::string, double> workload_efficiency;
};

struct HardwareQuery {
    double temperature_c = 25.0;
    double power_cap_w = 0.0;
    double clock_fraction = 1.0;
    double voltage_v = 1.0;
    double cumulative_dose_rad = 0.0;
    double dose_rate_rad_s = 0.0;
    double particle_flux = 0.0;
    std::string workload_class = "generic";
};

struct EnvelopeValue {
    double nominal = 0.0;
    double lower_bound = 0.0;
    double upper_bound = 0.0;
    double confidence = 1.0;
    bool extrapolated = false;
};

struct Provenance {
    std::string source;
    std::string device_model;
    std::string revision;
    std::string campaign;
    std::string manifest_sha256;
};

class HardwareEnvelopeProvider {
public:
    virtual ~HardwareEnvelopeProvider() = default;
    virtual EnvelopeValue throughput(const HardwareQuery& query) const = 0;
    virtual EnvelopeValue power(const HardwareQuery& query) const = 0;
    virtual EnvelopeValue failure_rate(const HardwareQuery& query) const = 0;
    virtual EnvelopeValue memory_error_rate(const HardwareQuery& query) const = 0;
    virtual EnvelopeValue degradation(const HardwareQuery& query) const = 0;
    virtual Provenance provenance() const = 0;
};

}  // namespace gmat_compute

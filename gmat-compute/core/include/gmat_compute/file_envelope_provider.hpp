#pragma once

#include "gmat_compute/hardware_profile.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace gmat_compute {

class FileEnvelopeProvider final : public HardwareEnvelopeProvider {
public:
    explicit FileEnvelopeProvider(const std::filesystem::path& manifest_path);
    EnvelopeValue throughput(const HardwareQuery& query) const override;
    EnvelopeValue power(const HardwareQuery& query) const override;
    EnvelopeValue failure_rate(const HardwareQuery& query) const override;
    EnvelopeValue memory_error_rate(const HardwareQuery& query) const override;
    EnvelopeValue degradation(const HardwareQuery& query) const override;
    Provenance provenance() const override;

private:
    struct PowerThroughputRow {
        double temperature_c = 0.0;
        double power_cap_w = 0.0;
        std::string workload_class;
        double throughput = 0.0;
        double power_w = 0.0;
        double lower = 0.0;
        double upper = 0.0;
    };

    struct RadiationRow {
        double cumulative_dose_rad = 0.0;
        double temperature_c = 0.0;
        double performance_factor = 1.0;
        double lower = 1.0;
        double upper = 1.0;
    };

    struct FaultRow {
        double particle_flux = 0.0;
        double temperature_c = 0.0;
        double power_w = 0.0;
        double fault_rate_per_hour = 0.0;
    };

    EnvelopeValue interpolate_power_throughput(const HardwareQuery& query,
                                               bool want_power) const;
    std::filesystem::path manifest_path_;
    std::filesystem::path base_dir_;
    std::string extrapolation_policy_ = "reject";
    Provenance provenance_;
    std::vector<PowerThroughputRow> power_rows_;
    std::vector<RadiationRow> radiation_rows_;
    std::vector<FaultRow> fault_rows_;
};

}  // namespace gmat_compute

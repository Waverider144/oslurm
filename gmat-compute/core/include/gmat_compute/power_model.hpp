#pragma once

#include "gmat_compute/environment.hpp"
#include "gmat_compute/compute_state.hpp"
#include "gmat_compute/hardware_profile.hpp"

#include <memory>

namespace gmat_compute {

struct ComputeLoad {
    double utilization = 0.0;
    double throughput_units_per_s = 0.0;
    std::string workload_class = "generic";
};

struct PowerResult {
    double requested_power_w = 0.0;
    double granted_power_w = 0.0;
    double device_power_w = 0.0;
    double generated_heat_w = 0.0;
    bool power_limited = false;
};

class PowerModel {
public:
    virtual ~PowerModel() = default;
    virtual PowerResult evaluate(const ComputeLoad& load,
                                 const OrbitalEnvironmentState& env,
                                 const ComputePayloadState& state) = 0;
};

class SimplePowerModel final : public PowerModel {
public:
    explicit SimplePowerModel(HardwareProfile hardware);
    PowerResult evaluate(const ComputeLoad& load,
                         const OrbitalEnvironmentState& env,
                         const ComputePayloadState& state) override;

private:
    HardwareProfile hardware_;
};

class EnvelopeDrivenPowerModel final : public PowerModel {
public:
    EnvelopeDrivenPowerModel(HardwareProfile hardware,
                             std::shared_ptr<HardwareEnvelopeProvider> provider);
    PowerResult evaluate(const ComputeLoad& load,
                         const OrbitalEnvironmentState& env,
                         const ComputePayloadState& state) override;

private:
    HardwareProfile hardware_;
    std::shared_ptr<HardwareEnvelopeProvider> provider_;
};

}  // namespace gmat_compute

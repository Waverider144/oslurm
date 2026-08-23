#pragma once

#include "gmat_compute/environment.hpp"
#include "gmat_compute/compute_state.hpp"
#include "gmat_compute/hardware_profile.hpp"

#include <memory>
#include <random>

namespace gmat_compute {

class ReliabilityModel {
public:
    virtual ~ReliabilityModel() = default;
    virtual ReliabilityState evaluate(const OrbitalEnvironmentState& env,
                                      const ComputePayloadState& state,
                                      double dt_s) = 0;
};

class NoFailureModel final : public ReliabilityModel {
public:
    ReliabilityState evaluate(const OrbitalEnvironmentState& env,
                              const ComputePayloadState& state,
                              double dt_s) override;
};

class SimplePoissonFailureModel final : public ReliabilityModel {
public:
    SimplePoissonFailureModel(double base_failure_rate_per_hour,
                              unsigned seed,
                              bool deterministic_expected_risk);
    ReliabilityState evaluate(const OrbitalEnvironmentState& env,
                              const ComputePayloadState& state,
                              double dt_s) override;

private:
    double base_failure_rate_per_hour_;
    bool deterministic_expected_risk_;
    std::mt19937 rng_;
    double cumulative_probability_ = 0.0;
    double expected_faults_ = 0.0;
    bool failed_ = false;
};

class EnvelopeDrivenReliabilityModel final : public ReliabilityModel {
public:
    explicit EnvelopeDrivenReliabilityModel(std::shared_ptr<HardwareEnvelopeProvider> provider);
    ReliabilityState evaluate(const OrbitalEnvironmentState& env,
                              const ComputePayloadState& state,
                              double dt_s) override;

private:
    std::shared_ptr<HardwareEnvelopeProvider> provider_;
    double cumulative_probability_ = 0.0;
};

}  // namespace gmat_compute

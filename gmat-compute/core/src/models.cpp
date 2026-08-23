#include "gmat_compute/accelerator.hpp"
#include "gmat_compute/compute_payload.hpp"
#include "gmat_compute/power_model.hpp"
#include "gmat_compute/reliability_model.hpp"
#include "gmat_compute/thermal_model.hpp"

#include <algorithm>
#include <cmath>

namespace gmat_compute {

SimplePowerModel::SimplePowerModel(HardwareProfile hardware) : hardware_(std::move(hardware)) {}

PowerResult SimplePowerModel::evaluate(const ComputeLoad& load,
                                       const OrbitalEnvironmentState& env,
                                       const ComputePayloadState&) {
    const double orbital_budget_w = env.in_sunlight ? hardware_.max_power_w : hardware_.max_power_w * 0.56;
    const double requested = hardware_.idle_power_w +
        (hardware_.nominal_power_w - hardware_.idle_power_w) * std::clamp(load.utilization, 0.0, 1.0);
    const double granted = std::min(requested, orbital_budget_w);
    return {requested, granted, granted, granted * 0.92, granted + 1e-9 < requested};
}

EnvelopeDrivenPowerModel::EnvelopeDrivenPowerModel(HardwareProfile hardware,
                                                   std::shared_ptr<HardwareEnvelopeProvider> provider)
    : hardware_(std::move(hardware)), provider_(std::move(provider)) {}

PowerResult EnvelopeDrivenPowerModel::evaluate(const ComputeLoad& load,
                                               const OrbitalEnvironmentState& env,
                                               const ComputePayloadState& state) {
    const double orbital_budget_w = env.in_sunlight ? hardware_.max_power_w : hardware_.max_power_w * 0.56;
    HardwareQuery query;
    query.temperature_c = state.thermal.temperature_c;
    query.power_cap_w = orbital_budget_w;
    query.cumulative_dose_rad = env.cumulative_radiation_dose_rad;
    query.dose_rate_rad_s = env.radiation_dose_rate_rad_s;
    query.workload_class = load.workload_class;
    const auto p = provider_->power(query);
    const double requested = std::max(hardware_.idle_power_w, p.nominal);
    const double granted = std::min(requested, orbital_budget_w);
    return {requested, granted, granted, granted * 0.92, granted + 1e-9 < requested};
}

FirstOrderRCThermalModel::FirstOrderRCThermalModel(double initial_temperature_c,
                                                   double thermal_capacity_j_per_c,
                                                   double thermal_resistance_c_per_w,
                                                   double throttle_temperature_c)
    : temperature_c_(initial_temperature_c),
      thermal_capacity_j_per_c_(thermal_capacity_j_per_c),
      thermal_resistance_c_per_w_(thermal_resistance_c_per_w),
      throttle_temperature_c_(throttle_temperature_c) {}

void FirstOrderRCThermalModel::step(double generated_heat_w,
                                    const OrbitalEnvironmentState& env,
                                    double dt_s) {
    const double external_c = env.external_temperature_k - 273.15;
    const double cooling_w = (temperature_c_ - external_c) / thermal_resistance_c_per_w_;
    temperature_c_ += (generated_heat_w - cooling_w) * dt_s / thermal_capacity_j_per_c_;
}

ThermalState FirstOrderRCThermalModel::state() const {
    return {temperature_c_, temperature_c_ >= throttle_temperature_c_};
}

ReliabilityState NoFailureModel::evaluate(const OrbitalEnvironmentState&,
                                          const ComputePayloadState&,
                                          double) {
    return {};
}

SimplePoissonFailureModel::SimplePoissonFailureModel(double base_failure_rate_per_hour,
                                                     unsigned seed,
                                                     bool deterministic_expected_risk)
    : base_failure_rate_per_hour_(base_failure_rate_per_hour),
      deterministic_expected_risk_(deterministic_expected_risk),
      rng_(seed) {}

ReliabilityState SimplePoissonFailureModel::evaluate(const OrbitalEnvironmentState& env,
                                                     const ComputePayloadState& state,
                                                     double dt_s) {
    double thermal_factor = std::max(1.0, std::exp((state.thermal.temperature_c - 60.0) / 35.0));
    double dose_factor = 1.0 + env.radiation_dose_rate_rad_s * 1000.0;
    double lambda = base_failure_rate_per_hour_ * thermal_factor * dose_factor * dt_s / 3600.0;
    expected_faults_ += lambda;
    cumulative_probability_ = 1.0 - std::exp(-expected_faults_);
    if (!deterministic_expected_risk_ && !failed_) {
        std::bernoulli_distribution dist(std::clamp(lambda, 0.0, 1.0));
        failed_ = dist(rng_);
    }
    return {cumulative_probability_, expected_faults_, failed_};
}

EnvelopeDrivenReliabilityModel::EnvelopeDrivenReliabilityModel(std::shared_ptr<HardwareEnvelopeProvider> provider)
    : provider_(std::move(provider)) {}

ReliabilityState EnvelopeDrivenReliabilityModel::evaluate(const OrbitalEnvironmentState& env,
                                                          const ComputePayloadState& state,
                                                          double dt_s) {
    HardwareQuery query;
    query.temperature_c = state.thermal.temperature_c;
    query.power_cap_w = state.granted_power_w;
    query.cumulative_dose_rad = env.cumulative_radiation_dose_rad;
    query.dose_rate_rad_s = env.radiation_dose_rate_rad_s;
    const auto rate = provider_->failure_rate(query);
    const double lambda = std::max(0.0, rate.nominal) * dt_s / 3600.0;
    cumulative_probability_ = 1.0 - (1.0 - cumulative_probability_) * std::exp(-lambda);
    return {cumulative_probability_, 0.0, false};
}

GenericAccelerator::GenericAccelerator(HardwareProfile hardware,
                                       std::shared_ptr<HardwareEnvelopeProvider> provider)
    : hardware_(std::move(hardware)), provider_(std::move(provider)) {}

double GenericAccelerator::throughput(const AcceleratorOperatingPoint& op,
                                      const WorkloadDescriptor& workload,
                                      const DeviceEnvironment& env) const {
    HardwareQuery query;
    query.temperature_c = env.temperature_c;
    query.power_cap_w = op.power_cap_w;
    query.clock_fraction = op.clock_fraction;
    query.voltage_v = op.voltage_v;
    query.cumulative_dose_rad = env.cumulative_dose_rad;
    query.dose_rate_rad_s = env.dose_rate_rad_s;
    query.particle_flux = env.particle_flux;
    query.workload_class = workload.workload_class;
    double base = hardware_.base_throughput_units_per_s;
    if (provider_) {
        base = provider_->throughput(query).nominal * provider_->degradation(query).nominal;
    }
    const double thermal = env.temperature_c <= hardware_.thermal_limit_c
        ? 1.0
        : std::max(0.20, 1.0 - (env.temperature_c - hardware_.thermal_limit_c) / 40.0);
    auto efficiency = hardware_.workload_efficiency.find(workload.workload_class);
    const double workload_factor = efficiency == hardware_.workload_efficiency.end() ? 1.0 : efficiency->second;
    return base * thermal * std::clamp(op.clock_fraction, 0.0, 1.0) * workload_factor;
}

double GenericAccelerator::power_draw_w(const AcceleratorOperatingPoint& op,
                                        const WorkloadDescriptor& workload,
                                        const DeviceEnvironment& env) const {
    if (provider_) {
        HardwareQuery query;
        query.temperature_c = env.temperature_c;
        query.power_cap_w = op.power_cap_w;
        query.workload_class = workload.workload_class;
        return provider_->power(query).nominal;
    }
    return std::min(hardware_.max_power_w, std::max(hardware_.idle_power_w, op.power_cap_w));
}

double GenericAccelerator::max_safe_power_w(const DeviceEnvironment& env) const {
    if (env.temperature_c >= hardware_.thermal_limit_c + 25.0) return hardware_.max_power_w * 0.35;
    if (env.temperature_c >= hardware_.thermal_limit_c) return hardware_.max_power_w * 0.65;
    return hardware_.max_power_w;
}

AcceleratorHealth GenericAccelerator::health(const DeviceEnvironment& env) const {
    const bool degraded = env.temperature_c > hardware_.thermal_limit_c || env.cumulative_dose_rad > 5000.0;
    const double dose_factor = env.cumulative_dose_rad > 0.0
        ? std::max(0.5, 1.0 - env.cumulative_dose_rad / 200000.0)
        : 1.0;
    return {dose_factor, degraded, false};
}

}  // namespace gmat_compute

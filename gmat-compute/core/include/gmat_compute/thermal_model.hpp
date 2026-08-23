#pragma once

#include "gmat_compute/environment.hpp"
#include "gmat_compute/compute_state.hpp"

namespace gmat_compute {

class ThermalModel {
public:
    virtual ~ThermalModel() = default;
    virtual void step(double generated_heat_w,
                      const OrbitalEnvironmentState& env,
                      double dt_s) = 0;
    virtual ThermalState state() const = 0;
};

class FirstOrderRCThermalModel final : public ThermalModel {
public:
    FirstOrderRCThermalModel(double initial_temperature_c,
                             double thermal_capacity_j_per_c,
                             double thermal_resistance_c_per_w,
                             double throttle_temperature_c);
    void step(double generated_heat_w,
              const OrbitalEnvironmentState& env,
              double dt_s) override;
    ThermalState state() const override;

private:
    double temperature_c_;
    double thermal_capacity_j_per_c_;
    double thermal_resistance_c_per_w_;
    double throttle_temperature_c_;
};

}  // namespace gmat_compute

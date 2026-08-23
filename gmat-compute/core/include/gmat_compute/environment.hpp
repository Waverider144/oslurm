#pragma once

#include <array>

namespace gmat_compute {

struct OrbitalEnvironmentState {
    double simulation_time_s = 0.0;
    bool in_sunlight = true;
    double solar_flux_w_m2 = 1361.0;
    double external_temperature_k = 255.0;
    double radiation_dose_rate_rad_s = 0.0;
    double cumulative_radiation_dose_rad = 0.0;
    std::array<double, 3> position_eci_m{0.0, 0.0, 0.0};
    std::array<double, 3> velocity_eci_mps{0.0, 0.0, 0.0};
};

struct DeviceEnvironment {
    double temperature_c = 25.0;
    double power_cap_w = 0.0;
    double cumulative_dose_rad = 0.0;
    double dose_rate_rad_s = 0.0;
    double particle_flux = 0.0;
};

}  // namespace gmat_compute

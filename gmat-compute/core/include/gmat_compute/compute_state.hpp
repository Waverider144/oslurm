#pragma once

#include "gmat_compute/hardware_profile.hpp"
#include "gmat_compute/compute_task.hpp"

#include <vector>

namespace gmat_compute {

struct ThermalState {
    double temperature_c = 25.0;
    bool throttling = false;
};

struct ReliabilityState {
    double failure_probability = 0.0;
    double expected_faults = 0.0;
    bool failed = false;
};

struct ComputePayloadState {
    double simulation_time_s = 0.0;
    bool in_sunlight = true;
    double battery_soc = 1.0;
    double power_cap_w = 0.0;
    double requested_power_w = 0.0;
    double granted_power_w = 0.0;
    double throughput_units_per_s = 0.0;
    ThermalState thermal;
    ReliabilityState reliability;
    std::vector<ComputeTaskState> tasks;
};

struct ForecastInterval {
    double start_s = 0.0;
    double end_s = 0.0;
    EnvelopeValue available_compute;
    EnvelopeValue power_budget_w;
    EnvelopeValue temperature_c;
    EnvelopeValue failure_probability;
    bool in_sunlight = true;
};

struct ComputeForecast {
    double valid_from_s = 0.0;
    double valid_until_s = 0.0;
    std::vector<ForecastInterval> intervals;
};

struct ForecastRequest {
    double start_s = 0.0;
    double horizon_s = 600.0;
    double step_s = 60.0;
};

}  // namespace gmat_compute

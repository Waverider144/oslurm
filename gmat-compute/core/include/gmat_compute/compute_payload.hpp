#pragma once

#include "gmat_compute/accelerator.hpp"
#include "gmat_compute/compute_state.hpp"
#include "gmat_compute/compute_task.hpp"
#include "gmat_compute/environment.hpp"
#include "gmat_compute/power_model.hpp"
#include "gmat_compute/reliability_model.hpp"
#include "gmat_compute/thermal_model.hpp"

#include <memory>
#include <unordered_map>

namespace gmat_compute {

class ComputePayload {
public:
    ComputePayload(HardwareProfile hardware,
                   std::unique_ptr<PowerModel> power,
                   std::unique_ptr<ThermalModel> thermal,
                   std::unique_ptr<ReliabilityModel> reliability,
                   std::unique_ptr<AcceleratorModel> accelerator);

    void step(const OrbitalEnvironmentState& env, double dt_s);
    TaskHandle submit(const ComputeTaskSpec& task);
    bool start(TaskHandle task);
    bool checkpoint(TaskHandle task);
    bool restore(TaskHandle task);
    bool cancel(TaskHandle task);
    ComputePayloadState state() const;
    ComputeForecast forecast(const ForecastRequest& request) const;

private:
    ComputeTaskState* find_task(const TaskHandle& task);
    const ComputeTaskState* find_task(const TaskHandle& task) const;
    double active_throughput(const OrbitalEnvironmentState& env,
                             const ComputePayloadState& state) const;

    HardwareProfile hardware_;
    std::unique_ptr<PowerModel> power_;
    std::unique_ptr<ThermalModel> thermal_;
    std::unique_ptr<ReliabilityModel> reliability_;
    std::unique_ptr<AcceleratorModel> accelerator_;
    ComputePayloadState state_;
};

}  // namespace gmat_compute

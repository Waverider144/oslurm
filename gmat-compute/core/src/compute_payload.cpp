#include "gmat_compute/compute_payload.hpp"

#include <algorithm>
#include <cmath>

namespace gmat_compute {

ComputePayload::ComputePayload(HardwareProfile hardware,
                               std::unique_ptr<PowerModel> power,
                               std::unique_ptr<ThermalModel> thermal,
                               std::unique_ptr<ReliabilityModel> reliability,
                               std::unique_ptr<AcceleratorModel> accelerator)
    : hardware_(std::move(hardware)),
      power_(std::move(power)),
      thermal_(std::move(thermal)),
      reliability_(std::move(reliability)),
      accelerator_(std::move(accelerator)) {
    state_.power_cap_w = hardware_.max_power_w;
    state_.thermal = thermal_->state();
}

ComputeTaskState* ComputePayload::find_task(const TaskHandle& task) {
    auto it = std::find_if(state_.tasks.begin(), state_.tasks.end(), [&](const auto& t) {
        return t.spec.id == task;
    });
    return it == state_.tasks.end() ? nullptr : &(*it);
}

const ComputeTaskState* ComputePayload::find_task(const TaskHandle& task) const {
    auto it = std::find_if(state_.tasks.begin(), state_.tasks.end(), [&](const auto& t) {
        return t.spec.id == task;
    });
    return it == state_.tasks.end() ? nullptr : &(*it);
}

double ComputePayload::active_throughput(const OrbitalEnvironmentState& env,
                                         const ComputePayloadState& state) const {
    DeviceEnvironment device_env;
    device_env.temperature_c = state.thermal.temperature_c;
    device_env.power_cap_w = state.granted_power_w;
    device_env.cumulative_dose_rad = env.cumulative_radiation_dose_rad;
    device_env.dose_rate_rad_s = env.radiation_dose_rate_rad_s;
    AcceleratorOperatingPoint op;
    op.power_cap_w = state.granted_power_w;
    op.clock_fraction = hardware_.max_power_w > 0.0
        ? std::clamp(state.granted_power_w / hardware_.max_power_w, 0.0, 1.0)
        : 1.0;
    WorkloadDescriptor workload;
    for (const auto& task : state.tasks) {
        if (task.status == TaskStatus::Running) {
            workload.workload_class = task.spec.workload_class;
            break;
        }
    }
    return accelerator_->throughput(op, workload, device_env);
}

void ComputePayload::step(const OrbitalEnvironmentState& env, double dt_s) {
    state_.simulation_time_s = env.simulation_time_s;
    state_.in_sunlight = env.in_sunlight;
    state_.thermal = thermal_->state();
    bool has_running = false;
    std::string workload = "generic";
    for (const auto& task : state_.tasks) {
        if (task.status == TaskStatus::Running) {
            has_running = true;
            workload = task.spec.workload_class;
            break;
        }
    }
    ComputeLoad load;
    load.utilization = has_running ? 1.0 : 0.0;
    load.workload_class = workload;
    const PowerResult power = power_->evaluate(load, env, state_);
    state_.requested_power_w = power.requested_power_w;
    state_.granted_power_w = power.granted_power_w;
    state_.power_cap_w = env.in_sunlight ? hardware_.max_power_w : hardware_.max_power_w * 0.56;
    thermal_->step(power.generated_heat_w, env, dt_s);
    state_.thermal = thermal_->state();
    state_.reliability = reliability_->evaluate(env, state_, dt_s);
    state_.throughput_units_per_s = has_running ? active_throughput(env, state_) : 0.0;
    const double completed = state_.throughput_units_per_s * dt_s;
    for (auto& task : state_.tasks) {
        if (task.status != TaskStatus::Running) continue;
        const double delta = std::min(task.remaining_compute_units, completed);
        task.remaining_compute_units -= delta;
        task.completed_compute_units += delta;
        if (task.remaining_compute_units <= 1e-9) {
            task.remaining_compute_units = 0.0;
            task.status = TaskStatus::Completed;
        }
        break;
    }
}

TaskHandle ComputePayload::submit(const ComputeTaskSpec& task) {
    ComputeTaskState state;
    state.spec = task;
    state.remaining_compute_units = task.required_compute_units;
    state_.tasks.push_back(state);
    return task.id;
}

bool ComputePayload::start(TaskHandle task) {
    auto* t = find_task(task);
    if (!t || t->status == TaskStatus::Completed || t->status == TaskStatus::Cancelled) return false;
    t->status = TaskStatus::Running;
    return true;
}

bool ComputePayload::checkpoint(TaskHandle task) {
    auto* t = find_task(task);
    if (!t || !t->spec.checkpointable || t->status != TaskStatus::Running) return false;
    t->status = TaskStatus::Checkpointed;
    return true;
}

bool ComputePayload::restore(TaskHandle task) {
    auto* t = find_task(task);
    if (!t || t->status != TaskStatus::Checkpointed) return false;
    t->status = TaskStatus::Running;
    return true;
}

bool ComputePayload::cancel(TaskHandle task) {
    auto* t = find_task(task);
    if (!t || t->status == TaskStatus::Completed) return false;
    t->status = TaskStatus::Cancelled;
    return true;
}

ComputePayloadState ComputePayload::state() const {
    return state_;
}

ComputeForecast ComputePayload::forecast(const ForecastRequest& request) const {
    ComputeForecast forecast;
    forecast.valid_from_s = request.start_s;
    forecast.valid_until_s = request.start_s + request.horizon_s;
    for (double t = request.start_s; t < forecast.valid_until_s; t += request.step_s) {
        const bool sunlight = std::fmod(t, 600.0) < 240.0;
        const double cap = sunlight ? hardware_.max_power_w : hardware_.max_power_w * 0.56;
        ForecastInterval interval;
        interval.start_s = t;
        interval.end_s = std::min(t + request.step_s, forecast.valid_until_s);
        interval.in_sunlight = sunlight;
        interval.power_budget_w = {cap, cap * 0.96, cap * 1.02, 0.9, false};
        interval.available_compute = {hardware_.base_throughput_units_per_s * cap / hardware_.max_power_w,
                                      hardware_.base_throughput_units_per_s * cap / hardware_.max_power_w * 0.92,
                                      hardware_.base_throughput_units_per_s * cap / hardware_.max_power_w * 1.04,
                                      0.86, false};
        interval.temperature_c = {state_.thermal.temperature_c, state_.thermal.temperature_c - 1.5,
                                  state_.thermal.temperature_c + 4.0, 0.78, false};
        interval.failure_probability = {state_.reliability.failure_probability,
                                        state_.reliability.failure_probability,
                                        std::min(1.0, state_.reliability.failure_probability + 0.002),
                                        0.75, false};
        forecast.intervals.push_back(interval);
    }
    return forecast;
}

}  // namespace gmat_compute

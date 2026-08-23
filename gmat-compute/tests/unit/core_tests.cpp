#include "gmat_compute/compute_payload.hpp"
#include "gmat_compute/curves.hpp"
#include "gmat_compute/file_envelope_provider.hpp"

#include <cassert>
#include <cmath>
#include <iostream>

using namespace gmat_compute;

static HardwareProfile gpu_profile() {
    HardwareProfile h;
    h.id = "generic_gpu";
    h.accelerator_model = "envelope";
    h.base_throughput_units_per_s = 480.0;
    h.nominal_power_w = 500.0;
    h.max_power_w = 500.0;
    h.idle_power_w = 60.0;
    h.thermal_limit_c = 78.0;
    h.workload_efficiency["gpu_fp16"] = 1.0;
    return h;
}

int main() {
    PiecewiseLinear1D curve({
        {0.0, {0.0, -0.1, 0.1, 0.9, false}},
        {10.0, {20.0, 19.0, 21.0, 0.9, false}}
    });
    auto b = curve.evaluate_bounds({5.0});
    assert(std::abs(b.nominal - 10.0) < 1e-9);
    assert(std::abs(b.lower_bound - 9.45) < 0.5);

    auto provider = std::make_shared<FileEnvelopeProvider>("measured/example_gpu/manifest.yaml");
    HardwareQuery q;
    q.temperature_c = 25.0;
    q.power_cap_w = 500.0;
    q.workload_class = "gpu_fp16";
    auto thr = provider->throughput(q);
    assert(thr.nominal == 480.0);
    assert(!thr.extrapolated);
    q.power_cap_w = 1000.0;
    auto outside = provider->throughput(q);
    assert(outside.extrapolated);

    auto hardware = gpu_profile();
    ComputePayload payload(
        hardware,
        std::make_unique<EnvelopeDrivenPowerModel>(hardware, provider),
        std::make_unique<FirstOrderRCThermalModel>(45.0, 5000.0, 0.35, hardware.thermal_limit_c),
        std::make_unique<SimplePoissonFailureModel>(0.0001, 42, true),
        std::make_unique<GenericAccelerator>(hardware, provider));

    ComputeTaskSpec task;
    task.id = "unit-task";
    task.required_compute_units = 1000.0;
    task.required_memory_bytes = 128 * 1024 * 1024;
    task.checkpointable = true;
    task.checkpoint_size_bytes = 16 * 1024 * 1024;
    task.deadline_s = 300.0;
    task.workload_class = "gpu_fp16";
    auto handle = payload.submit(task);
    assert(payload.start(handle));

    OrbitalEnvironmentState env;
    env.in_sunlight = true;
    env.simulation_time_s = 0.0;
    env.external_temperature_k = 250.0;
    payload.step(env, 1.0);
    const double sunlight_thr = payload.state().throughput_units_per_s;
    assert(sunlight_thr > 400.0);

    assert(payload.checkpoint(handle));
    assert(payload.restore(handle));

    env.in_sunlight = false;
    env.simulation_time_s = 2.0;
    payload.step(env, 1.0);
    const double eclipse_thr = payload.state().throughput_units_per_s;
    assert(eclipse_thr < sunlight_thr);
    assert(payload.state().thermal.temperature_c > 45.0);

    auto forecast = payload.forecast({0.0, 180.0, 60.0});
    assert(forecast.intervals.size() == 3);
    assert(forecast.intervals[0].available_compute.confidence > 0.0);

    std::cout << "core tests passed\n";
    return 0;
}

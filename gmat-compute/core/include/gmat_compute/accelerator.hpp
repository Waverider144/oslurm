#pragma once

#include "gmat_compute/environment.hpp"
#include "gmat_compute/hardware_profile.hpp"

#include <memory>
#include <string>
#include <vector>

namespace gmat_compute {

struct AcceleratorOperatingPoint {
    double power_cap_w = 0.0;
    double clock_fraction = 1.0;
    double voltage_v = 1.0;
};

struct WorkloadDescriptor {
    std::string workload_class = "generic";
};

struct AcceleratorHealth {
    double performance_factor = 1.0;
    bool degraded = false;
    bool failed = false;
};

struct PerformanceContext {
    HardwareProfile hardware;
    AcceleratorOperatingPoint op;
    WorkloadDescriptor workload;
    DeviceEnvironment device_env;
    AcceleratorHealth health;
};

class AcceleratorModel {
public:
    virtual ~AcceleratorModel() = default;
    virtual double throughput(const AcceleratorOperatingPoint& op,
                              const WorkloadDescriptor& workload,
                              const DeviceEnvironment& env) const = 0;
    virtual double power_draw_w(const AcceleratorOperatingPoint& op,
                                const WorkloadDescriptor& workload,
                                const DeviceEnvironment& env) const = 0;
    virtual double max_safe_power_w(const DeviceEnvironment& env) const = 0;
    virtual AcceleratorHealth health(const DeviceEnvironment& env) const = 0;
};

class PerformanceModifier {
public:
    virtual ~PerformanceModifier() = default;
    virtual double factor(const PerformanceContext& context) const = 0;
};

class GenericAccelerator final : public AcceleratorModel {
public:
    GenericAccelerator(HardwareProfile hardware,
                       std::shared_ptr<HardwareEnvelopeProvider> provider = nullptr);
    double throughput(const AcceleratorOperatingPoint& op,
                      const WorkloadDescriptor& workload,
                      const DeviceEnvironment& env) const override;
    double power_draw_w(const AcceleratorOperatingPoint& op,
                        const WorkloadDescriptor& workload,
                        const DeviceEnvironment& env) const override;
    double max_safe_power_w(const DeviceEnvironment& env) const override;
    AcceleratorHealth health(const DeviceEnvironment& env) const override;

private:
    HardwareProfile hardware_;
    std::shared_ptr<HardwareEnvelopeProvider> provider_;
};

}  // namespace gmat_compute

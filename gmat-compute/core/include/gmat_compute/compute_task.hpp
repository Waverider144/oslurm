#pragma once

#include <cstdint>
#include <string>

namespace gmat_compute {

using TaskHandle = std::string;

struct ComputeTaskSpec {
    std::string id;
    double required_compute_units = 0.0;
    uint64_t required_memory_bytes = 0;
    uint64_t required_storage_bytes = 0;
    uint64_t input_bytes = 0;
    uint64_t output_bytes = 0;
    bool checkpointable = false;
    uint64_t checkpoint_size_bytes = 0;
    double deadline_s = 0.0;
    int priority = 0;
    std::string workload_class = "generic";
};

enum class TaskStatus {
    Queued,
    Running,
    Checkpointed,
    Completed,
    Cancelled,
    Failed
};

struct ComputeTaskState {
    ComputeTaskSpec spec;
    TaskStatus status = TaskStatus::Queued;
    double remaining_compute_units = 0.0;
    double completed_compute_units = 0.0;
};

}  // namespace gmat_compute

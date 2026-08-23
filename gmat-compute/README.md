# GMAT-Compute

A scheduler-neutral compute-payload extension for orbital mission simulation.

GMAT-Compute turns orbital mission state into a compute-payload digital twin. It
does not schedule jobs by itself and it is not an O-SLURM private component.

```text
Orbital Environment
        ↓
Compute Hardware Model
        ↓
Task Execution Model
        ↓
Scheduler API
```

The core has zero GMAT, Slurm, or O-SLURM dependency. GMAT-specific code lives
under `adapters/gmat/` and `plugin/gmat/`.

## Quick Start

```bash
make test
make demo
```

`make demo` requires a real GMAT executable. It does not use a mock GMAT path
and will not report PASS when GMAT is unavailable.

Current verified status:

```text
GMAT Runtime Integration: REAL
GMAT Plugin: PARTIAL
Hardware model: FILE ENVELOPE
Scheduler API: PROTO + Python client example
```

## What It Provides

- A C++ compute-payload core independent of GMAT internals.
- A real GMAT adapter using `GmatConsole` report output.
- A file-based measured-envelope provider.
- A Python provider ABI for lab models.
- A scheduler-neutral protobuf API.
- A deterministic GMAT-to-compute demo.

## Repository Map

```text
core/include/gmat_compute/       Public C++ API
core/src/                        Core implementation
adapters/gmat/                   Real GMAT console adapter
plugin/gmat/                     Reserved compiled GMAT plugin shell
profiles/                        Hardware profile examples
measured/example_gpu/            Example measured envelope
api/proto/                       Scheduler-neutral gRPC/protobuf contract
api/python/gmat_compute/         Python provider ABI
examples/scheduler_client/       External scheduler client shape
tools/calibrate/                 Manifest validation tools
docs/                            Detailed design notes
```

## Core C++ API

The main entry point is:

```cpp
#include "gmat_compute/compute_payload.hpp"
```

Minimal usage:

```cpp
using namespace gmat_compute;

HardwareProfile hardware;
hardware.id = "generic_gpu";
hardware.base_throughput_units_per_s = 480.0;
hardware.max_power_w = 500.0;

auto provider = std::make_shared<FileEnvelopeProvider>(
    "measured/example_gpu/manifest.yaml");

ComputePayload payload(
    hardware,
    std::make_unique<EnvelopeDrivenPowerModel>(hardware, provider),
    std::make_unique<FirstOrderRCThermalModel>(45.0, 5000.0, 0.35, 78.0),
    std::make_unique<EnvelopeDrivenReliabilityModel>(provider),
    std::make_unique<GenericAccelerator>(hardware, provider));

ComputeTaskSpec task;
task.id = "demo-inference-001";
task.required_compute_units = 160000.0;
task.required_memory_bytes = 2ull * 1024 * 1024 * 1024;
task.checkpointable = true;
task.workload_class = "gpu_fp16";

auto handle = payload.submit(task);
payload.start(handle);

OrbitalEnvironmentState env;
env.simulation_time_s = 120.0;
env.in_sunlight = true;
env.solar_flux_w_m2 = 1361.0;
env.external_temperature_k = 255.0;

payload.step(env, 60.0);
auto state = payload.state();
```

`ComputePayload` supports:

```cpp
TaskHandle submit(const ComputeTaskSpec& task);
bool start(TaskHandle task);
bool checkpoint(TaskHandle task);
bool restore(TaskHandle task);
bool cancel(TaskHandle task);
void step(const OrbitalEnvironmentState& env, double dt_s);
ComputePayloadState state() const;
ComputeForecast forecast(const ForecastRequest& request) const;
```

## Environment Contract

GMAT-Compute core only consumes this scheduler-neutral state:

```cpp
struct OrbitalEnvironmentState {
    double simulation_time_s;
    bool in_sunlight;
    double solar_flux_w_m2;
    double external_temperature_k;
    double radiation_dose_rate_rad_s;
    double cumulative_radiation_dose_rad;
    std::array<double, 3> position_eci_m;
    std::array<double, 3> velocity_eci_mps;
};
```

Adapters may compute missing values. The core never includes GMAT headers.

## Task Contract

Task work is expressed in workload-normalized compute units, not fixed runtime
or FLOP-only semantics:

```cpp
struct ComputeTaskSpec {
    std::string id;
    double required_compute_units;
    uint64_t required_memory_bytes;
    uint64_t required_storage_bytes;
    uint64_t input_bytes;
    uint64_t output_bytes;
    bool checkpointable;
    uint64_t checkpoint_size_bytes;
    double deadline_s;
    int priority;
    std::string workload_class;
};
```

Runtime evolves as:

```text
remaining_work(t + dt) =
remaining_work(t) - effective_throughput(t) * dt
```

`effective_throughput` can react to power cap, temperature, thermal throttling,
radiation degradation, device health, and workload class.

## Hardware Envelope Provider

All measured hardware behavior enters through:

```cpp
class HardwareEnvelopeProvider {
public:
    virtual EnvelopeValue throughput(const HardwareQuery&) const = 0;
    virtual EnvelopeValue power(const HardwareQuery&) const = 0;
    virtual EnvelopeValue failure_rate(const HardwareQuery&) const = 0;
    virtual EnvelopeValue memory_error_rate(const HardwareQuery&) const = 0;
    virtual EnvelopeValue degradation(const HardwareQuery&) const = 0;
    virtual Provenance provenance() const = 0;
};
```

Query:

```cpp
struct HardwareQuery {
    double temperature_c;
    double power_cap_w;
    double clock_fraction;
    double voltage_v;
    double cumulative_dose_rad;
    double dose_rate_rad_s;
    double particle_flux;
    std::string workload_class;
};
```

Return value:

```cpp
struct EnvelopeValue {
    double nominal;
    double lower_bound;
    double upper_bound;
    double confidence;
    bool extrapolated;
};
```

Out-of-domain queries must not be silent. The manifest defines the extrapolation
policy and providers mark `extrapolated=true` when used.

## Measured Envelope Manifest

Example:

```yaml
schema_version: 1

device:
  vendor: example
  model: experimental_gpu_01
  revision: revA

provenance:
  source: laboratory_measurement
  test_campaign: TVAC_RAD_2027_01

units:
  temperature: C
  power: W
  throughput: workload_units_per_s

axes:
  power_throughput:
    - temperature_c
    - power_cap_w
    - workload_class

interpolation:
  method: nearest_linear_v1

extrapolation:
  policy: clamp

datasets:
  power_throughput:
    file: power_throughput.csv
  radiation_degradation:
    file: radiation_degradation.csv
  fault_rate:
    file: fault_rate.csv
```

Validate:

```bash
python3 tools/calibrate/validate_manifest.py measured/example_gpu/manifest.yaml
```

## Python Provider ABI

Laboratory teams can provide device behavior in Python without touching C++:

```python
from api.python.gmat_compute.provider import (
    EnvelopeValue,
    HardwareEnvelopeProvider,
    HardwareQuery,
)

class DeviceXEnvelope(HardwareEnvelopeProvider):
    def throughput(self, query: HardwareQuery) -> EnvelopeValue:
        return EnvelopeValue(
            nominal=480.0,
            lower_bound=462.0,
            upper_bound=495.0,
            confidence=0.9,
            extrapolated=False,
        )

    def power(self, query: HardwareQuery) -> EnvelopeValue:
        ...

    def failure_rate(self, query: HardwareQuery) -> EnvelopeValue:
        ...

    def memory_error_rate(self, query: HardwareQuery) -> EnvelopeValue:
        ...

    def degradation(self, query: HardwareQuery) -> EnvelopeValue:
        ...
```

See `providers/python/example_provider.py`.

## GMAT Adapter Contract

The current real integration is:

```bash
python3 adapters/gmat/gmat_ephemeris.py \
  --gmat ../third_party/GMAT-R2026a-fixed/bin/GmatConsole \
  --output build/demo/gmat-events.json
```

Output format:

```json
{
  "samples": [
    {
      "node_id": "sat002",
      "timestamp_ms": 1787357040000,
      "position_eci_m": [ ... ],
      "velocity_eci_mps": [ ... ],
      "in_sunlight": false
    }
  ],
  "events": [
    {
      "type": "ECLIPSE_ENTRY",
      "node_id": "sat002",
      "timestamp_ms": 1787357040000
    }
  ]
}
```

The adapter maps GMAT spacecraft names to compute node ids. A future compiled
GMAT plugin should preserve this contract and remain thin.

## Scheduler API

The protobuf contract is `api/proto/compute_simulation.proto`.

Service surface:

```protobuf
service ComputeSimulation {
  rpc ListNodes(ListNodesRequest) returns (ListNodesResponse);
  rpc GetState(GetStateRequest) returns (ComputeNodeState);
  rpc GetForecast(ForecastRequest) returns (ComputeForecast);
  rpc SubmitTask(SubmitTaskRequest) returns (TaskHandle);
  rpc PlaceTask(PlaceTaskRequest) returns (PlacementResult);
  rpc CheckpointTask(CheckpointRequest) returns (CheckpointResult);
  rpc RestoreTask(RestoreRequest) returns (RestoreResult);
  rpc CancelTask(CancelRequest) returns (CancelResult);
  rpc AdvanceTo(AdvanceRequest) returns (SimulationEvents);
}
```

No `SlurmJob`, `OslurmNode`, or GMAT internal type appears in the API.

External scheduler shape:

```python
nodes = sim.list_nodes()

for node in nodes:
    state = sim.get_state(node)
    forecast = sim.get_forecast(node, horizon=600)

# scheduler decides externally
sim.place_task(task, node="sat002")
```

See `examples/scheduler_client/client.py`.

## Deterministic Demo

```bash
make demo
```

Expected headline:

```text
GMAT backend: REAL
ECLIPSE_ENTRY
available compute power=280 W
throughput=125.95 units/s
Task completed=YES
GMAT ↔ COMPUTE CO-SIM:
PASS
```

## Branching Strategy

Yes, this is now coherent enough to maintain on its own branches, and probably
eventually as its own repository.

Recommended branches:

- `main`: passing build/test/demo only.
- `core`: C++ model APIs, task execution, forecasting.
- `gmat-adapter`: console adapter and future GMAT plugin work.
- `providers`: file/Python/measured envelope providers.
- `api`: protobuf, Python/C++ client contracts.
- `docs`: user docs, examples, interface specifications.

For this monorepo/subdirectory phase, use branch names such as:

```text
gmat-compute/core
gmat-compute/gmat-adapter
gmat-compute/providers
gmat-compute/api
```

Once the interface stabilizes, split `gmat-compute/` into a standalone repo and
keep O-SLURM as a downstream adapter/client rather than a dependency.

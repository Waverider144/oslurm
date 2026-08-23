# Architecture

GMAT-Compute separates mission state, hardware physics, task evolution, and
scheduler control.

```text
GMAT Spacecraft / external orbit source
        ↓
OrbitalEnvironmentState
        ↓
ComputePayload
        ↓
PowerModel + ThermalModel + ReliabilityModel + AcceleratorModel
        ↓
ComputePayloadState / ComputeForecast
        ↓
Scheduler-neutral API
```

The core API contains no GMAT internal classes and no scheduler-specific types.
Schedulers can query state, query forecasts, place tasks, checkpoint, restore,
cancel, and advance simulation time.

Performance is provider-composed. The first implementation combines file
envelope throughput, power caps, thermal derating, radiation degradation, and
reliability state without hardcoding a vendor accelerator type.

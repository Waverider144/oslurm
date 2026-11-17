# O-SLURM Flight Core (C++17, C ABI)

This is the first embedded decision/compute port, not a C++ rewrite of GMAT,
Slurm, Mission Control or the host simulator. The flight archive has no OS,
Python, NumPy, network, heap, exceptions, RTTI or logging dependency.

## Build and Test

```bash
make flight-test
flight/build/flight_benchmark
make flight-riscv
```

Host outputs: `flight/build/liboslurm_flight.a` and
`liboslurm_flight_host.so`. The shared library is only for host regression and
Python interoperability. `make test` builds it before running the Python suite.
`ctest` covers no-allocation decisions, expiry, replay, capacity and C linkage;
the Python suite reuses the satellite policy acceptance cases, compares 500
seeded randomized decisions and checks C++ CG against the Python reference.

RISC-V output: `flight/build-riscv/liboslurm_flight.a`, compiled with Clang for
`riscv32-unknown-elf`, `rv32imac`, `ilp32`, freestanding and size-optimized.
The example C adapter is also cross-compiled. The RV32 archive deliberately
excludes float64 CG: `-DOSLURM_ENABLE_CG=OFF`. No floating-point instructions or
FPU are needed for decisions. A C runtime providing `memset` and compiler-rt's
64-bit unsigned division helper is required when linking final firmware.

The toolchain file is an example for the current Clang installation, not a
board BSP. Bring the public header and source/library into your existing
firmware build, or supply your own CMake toolchain. Boot code, linker script,
interrupts, monotonic clock, watchdog, persistent state and radio drivers belong
to that platform integration. No board execution, target WCET or electrical
power consumption has yet been measured. Host benchmark numbers are not a
substitute for those measurements.

## Embedded Contract

`include/oslurm_flight.h` is C compatible. Do not transmit its raw structs over
the wire: alignment and endianness are ABI-specific. The host binding is
`oslurm/cpp.py`; the event entry-point example is `examples/agent.c`.

- At most 16 candidates, sorted by provisioned stable node ID. Larger inputs
  fail closed. The decision path is a bounded scan, not dynamic sorting.
- Resource/forecast inputs are provided by the caller. SoC uses ppm,
  temperatures milli-Celsius, durations milliseconds and absolute clock/lease
  values uint64 milliseconds. Quantization rounds safety floors down and costs
  up in the Python bridge. Thermal admission limits are 1..2000 C. Invalid
  values return `OSLURM_INVALID`, never an execution grant.
- Gates cover authority, CPU, RAM, accelerator eligibility, reserve, thermal
  limit, available window, deadline, advertisement expiry and busy reservation.
  Candidate windows must describe currently available capacity. Accelerator
  capability matching and forecast generation remain caller responsibilities.
- Selection maximizes the worst normalized margin at 1 ppm resolution, then
  minimizes completion time, migration cost, energy cost and stable node order.
  Sub-ppm ties may differ from Python floating-point ranking; feasibility must
  still pass. The bridge rechecks a selected candidate against Python gates.
- Eight fixed reservation slots. Offer/accept, commit, expire and release are
  explicit transitions; duplicate/expired commits fail. Accepted leases expire
  at `now >= expires_ms`; committed work requires explicit release/abort policy.
  Sequence high-water marks are maintained for 16 provisioned senders. Restore
  them from persistent storage or use a fresh authenticated boot epoch after
  reset; zero-initialization alone does not protect against cross-boot replay.
  The lease API manages slot lifecycle, not aggregate CPU/RAM accounting;
  caller admission must reserve those resources before accepting a task.
- Call on a telemetry, intent, neighbor or job event. `oslurm_next_wake` reports
  the earliest accepted-lease deadline, or UINT64_MAX when no timer is armed.
  The board can then sleep until an interrupt; there is no internal busy loop.
  All mutation is single-owner; serialize calls from ISR/RTOS contexts.
- The current Python orbital adapter uses the C++ decision function, while its
  host offer/commit message transport and journal remain Python. Deployable
  firmware should use the fixed C lease API, not those host dictionaries.

The workspace benchmark reports the request, candidate array, result and lease
table sizes. It excludes caller-owned telemetry, checkpoint buffers and stack;
compiler `.su` files provide build-specific stack estimates. Decision logic
does not allocate. The unit binary overrides allocation operators to abort.

## Actual Execution

```bash
python3 -m oslurm.joint_execution --solver cpp --transport tcp --publish
python3 -m oslurm.orbit_benchmark --decision-core cpp --backend local
```

The joint mission selects a compute node, runs the C++ CG kernel, checks the
true Ax=b residual in Python and again on the received ground artifact. The
same worker supports Slurm with `--backend slurm`. The numerical kernel owns
no buffers: the caller supplies disjoint dimension-sized float64 x/r/p/scratch
arrays and a bounded iteration budget. No file format or allocator is linked
into that kernel. One call accepts at most 256 iterations and dimensions up to
1048576; the host adapter chunks larger budgets so firmware can yield between
quanta. Optional float64 CG on a soft-float MCU is not recommended as
a low-power default; use an FPU-capable compute payload or a dedicated backend.

No flight certification is claimed. Radiation faults, redundant execution,
watchdog integration, authenticated control transport and measured hardware
energy budgets remain system-level validation work.

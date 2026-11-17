# Validation: 2026-11-17

## Regressions

`PYTHONPATH=/tmp/oslurm-browser-deps make regression` passed with local socket
permission. Playwright was installed in that temporary directory; normal setups
can install `requirements-dev.txt` instead.

| Component | Result |
| --- | --- |
| Main Python suite | 125 passed, including actual TCP tests; no socket skips |
| GMAT provider suite | 1 passed |
| C++ flight unit tests and C ABI executable | 2 passed, assertions enabled in Release |
| Python/C++ policy comparison | Existing policy cases plus 500 seeded randomized cases passed |
| RISC-V cross-build | RV32IMAC/ILP32 static archive and C example built; ELF machine verified |
| GMAT-Comm | C++ core and Python provider tests passed |
| Visualization | JS syntax/replay/ground-track checks passed |
| Real Chrome | Map pixels, selection, pan/zoom, time evolution, fixed inspector, telemetry reset/missing data, desktop/mobile layout passed |

The legacy closed-loop integration test formerly assumed Slurm must be absent.
It now checks the real process outcome and separately forces a missing-Slurm
branch, so successful real execution no longer causes a spurious test failure.

## Real Joint Mission

```bash
python3 -m oslurm.joint_execution --backend slurm --solver cpp \
  --transport tcp --deadline-s 300 --publish
```

Run: `joint-axb-d06e433e1d63`, Slurm job **89**, actual worker `sat004`.

- Real GMAT native EarthFixed/EarthMJ2000Eq states, JGM2 8x8 + Sun/Luna,
  1 s contact intervals with five-point screening.
- Packaged EOP coverage checked; native frame rotations and GMAT solar direction
  exported to the same-run viewer. Common-epoch 1 s versus 5 s propagation
  outputs agreed within the regression tolerance of 0.1 m. This is a consistency
  check, not evidence of absolute orbit accuracy.
- Real C++ solve: dimension 65536, 1007 iterations, independently verified true
  relative residual approximately `9.90008823e-9`.
- Both 1,575,108-byte payloads passed through actual TCP loopback, with receiver
  SHA256 acknowledgement and ground-side solution verification.
- Simulation latency approximately **24.9011 s**: input 11.4400 s + measured
  worker 2.0211 s + result 11.4400 s. Modeled RF contact/acquisition/serialization
  is separate from actual host TCP wall time (approximately 0.014 s total).
- Detailed result, mission profile, contact plan, Perfetto and replay artifacts
  are under `profiles/joint-axb-d06e433e1d63/` (ignored by Git). The replay is
  published in `docs/visualization/execution-trace.json`.

## Embedded Autonomy

```bash
python3 -m oslurm.orbit_benchmark --decision-core cpp --backend local --dimension 65536
```

Run: `orbit-axb-8ce22825b647`: real GMAT legacy full-orbit experiment, 27 C++
decisions, 4 committed checkpoint handoffs, no ground-dependent decisions,
1007 iterations and converged residual below 1e-8. This experiment intentionally
retains its legacy orbital/shadow/transport model; it tests the C++ decision
adapter separately from the native-frame joint runner.

Host benchmark: 100000 bounded 16-candidate decisions, roughly 0.1 microseconds
per call in this run, with 1156 bytes for the declared request/candidate/result/
lease workspace. The size excludes caller-owned data and stack. The RV32
decision object contains about 1690 bytes of text in this build and references
only compiler/runtime helpers, not heap or OS symbols. These are not target
RISC-V timing, WCET or measured power results.

## Not Validated

No physical RISC-V board, RF equipment, radiation/fault injection, flight
certification, live sensor estimation or electrical power measurement was used.
Drag/SRP, penumbra, terrain and covariance are still model boundaries. TCP is a
loopback integration backend, not an authenticated encrypted remote endpoint.
Firmware deployment still needs board startup, clock/timer/ISR ownership,
runtime helpers, persistent replay protection, watchdog and transport drivers.

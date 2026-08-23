# Demo

Run:

```bash
make demo
```

The demo:

1. Runs real GMAT `GmatConsole`.
2. Propagates four spacecraft.
3. Converts GMAT report output into ECI environment samples.
4. Feeds `sat002` into `ComputePayload`.
5. Detects eclipse via sunlight state.
6. Applies lower power cap.
7. Produces lower throughput.
8. Completes the task deterministically.

Expected headline:

```text
GMAT ↔ COMPUTE CO-SIM:
PASS
```

If real GMAT is unavailable, the command fails instead of reporting PASS.

# GMAT Integration

The adapter contract is:

```bash
python3 providers/gmat/adapter.py --scenario providers/gmat/scenarios/leo_demo.yaml --output /tmp/gmat-events.json
```

Backend detection order:

1. GMAT Python API module named `gmat` or `GMAT`.
2. `third_party/GMAT-R2026a-fixed/bin/GmatConsole`.
3. `third_party/GMAT-R2026a/bin/GmatConsole`.
4. `GmatConsole` or `GMAT` executable in `PATH`.
5. Explicit mock mode only when `--allow-mock` is provided.

`third_party/GMAT-R2026a-fixed` runs successfully through the subprocess backend. The adapter writes a report-only GMAT script, invokes:

```bash
GmatConsole --run <script> --exit --verbose off
```

and parses the generated report into O-SLURM JSON. Eclipse entry/exit events are currently derived from the real GMAT ECI ephemeris using a cylindrical Earth shadow test.

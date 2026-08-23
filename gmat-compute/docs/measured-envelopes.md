# Measured Envelopes

Measured envelopes let laboratory data replace analytic assumptions without
changing core code.

Workflow:

1. Measure the device in relevant conditions.
2. Export CSV or a future table format.
3. Create a versioned manifest.
4. Run `python tools/calibrate/validate_manifest.py measured/example_gpu/manifest.yaml`.
5. Run simulation with an envelope provider.
6. Compare analytic and measured model outputs.

Manifest files must record units, axes, interpolation method, extrapolation
policy, and provenance.

Envelope queries return:

```text
nominal
lower_bound
upper_bound
confidence
extrapolated
```

Out-of-domain queries are never silent. The manifest chooses `reject`, `clamp`,
`linear`, or a future `analytic_fallback`.

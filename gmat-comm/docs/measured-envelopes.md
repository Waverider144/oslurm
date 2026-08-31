# Measured Envelopes

Measured envelopes are CSV curves referenced by a manifest. Each row uses range in kilometers and conservative bounds:

```text
range_km,nominal,lower,upper,confidence
```

The C++ and Python providers interpolate within the measured range. Outside the range, the manifest policy decides whether values are clamped or rejected. The included example uses `reject` so out-of-domain links produce zero useful capability with `extrapolated=true`.

# Manifest Schema

Required fields:

- `schema_version`
- `terminal.vendor`, `terminal.model`, `terminal.revision`
- `provenance.source`, `provenance.campaign`, `provenance.measured_at`
- `axes.range.unit`
- `datasets.bandwidth.file`
- `extrapolation.policy`

The first C++ provider rejects out-of-domain range queries when
`extrapolation.policy: reject` and marks returned values as extrapolated.

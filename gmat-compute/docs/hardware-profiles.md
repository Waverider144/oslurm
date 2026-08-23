# Hardware Profiles

Profiles describe compute-payload configuration and select providers.

```yaml
accelerator:
  model: envelope
  envelope_provider:
    type: file
    manifest: measured/example_gpu/manifest.yaml
```

The core knows `AcceleratorModel`, not products. `profiles/h100_like_example.yaml`
is illustrative only and marks itself as not flight-qualified.

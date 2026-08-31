# Routing API

The current API exposes two deterministic route families:

- `continuous_plans(intent, contacts, max_plans)`: direct end-to-end contacts.
- `temporal_plans(intent, contacts, buffer, max_plans)`: two-hop store-carry-forward through an intermediate buffer.

Plans include hop timing, conservative transferred bytes, bottleneck bandwidth, latency, confidence, survival probability, and contact margin. Sorting is deterministic so tests and scheduler decisions are reproducible.

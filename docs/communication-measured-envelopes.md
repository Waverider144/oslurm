# Communication Measured Envelopes

GMAT-Comm measured envelopes live under `gmat-comm/measured`. They provide bandwidth, latency, packet-loss, acquisition, and power curves with provenance.

O-SLURM does not treat those files as orbital truth. GMAT provides geometry, GMAT-Comm maps geometry to communication capability, and O-SLURM uses the resulting contact windows to reserve data movement.

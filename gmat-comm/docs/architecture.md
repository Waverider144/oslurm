# GMAT-Comm Architecture

GMAT-Comm is split into a pure communication core and thin integration edges.

The core receives `CommunicationEnvironmentState` records and terminal profiles. It evaluates terminal capability through a `CommunicationEnvelopeProvider`, creates `ContactWindow` records, and supports route planning and reservation accounting. It does not include GMAT or Slurm headers.

Adapters are responsible for translating external truth into core records:

- GMAT adapter: ECI state history to geometry contacts.
- Python provider: measured or analytic envelope implementation for rapid studies.
- O-SLURM network layer: contact windows and transfer plans to scheduler decisions.

This keeps GMAT orbital propagation, communication payload modeling, and distributed scheduling independently testable.

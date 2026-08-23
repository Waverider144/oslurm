# Scheduler API

The API is scheduler-neutral and defined in `api/proto/compute_simulation.proto`.

It deliberately does not contain Slurm, O-SLURM, or GMAT internal types.

External schedulers can:

- list nodes
- get state
- get forecast
- submit task
- place task
- checkpoint
- restore
- cancel
- advance simulation

See `examples/scheduler_client/client.py` for the intended client shape.

# Communication Profiles

Profiles describe reusable terminal and relay assumptions for design studies. Public examples must be treated as approximations unless a profile says `operator_validated: true`.

Profile fields are intentionally simple YAML so they can be loaded by C++, Python, or O-SLURM tooling:

- `profile_id`
- `snapshot_date`
- `operator_validated`
- `terminals`
- `buffer`
- `envelope`

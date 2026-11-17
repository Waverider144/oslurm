const assert = require("node:assert/strict");
const fs = require("node:fs");
const { ExecutionTraceReplay } = require("../docs/visualization/execution-replay.js");

const bundle = JSON.parse(fs.readFileSync("docs/visualization/execution-trace.json", "utf8"));
const replay = new ExecutionTraceReplay(bundle);
const steps = replay.steps();
assert.equal(replay.indexAt(0), 0);
assert.equal(replay.indexAt(-1), 0);
assert.equal(replay.indexAt((replay.timestamps[1] - replay.epochMs) / 1000), 1);
assert.ok(replay.indexAt(replay.horizonS) <= replay.timestamps.length - 1);
assert.equal(steps.at(-1).dt, replay.durationMs);
assert.ok(steps.every((step, index) => index === 0 || step.simS >= steps[index - 1].simS));
assert.ok(steps.filter(step => step.source === "scheduler").every(step => step.kind === "SCHEDULER_DECISION"));
assert.equal(steps.filter(step => step.kind === "JOB_PROGRESS").length,
  bundle.events.filter(event => event.header.event_type === "JOB_PROGRESS").length);
const failedBundle = structuredClone(bundle);
failedBundle.result.converged = false;
assert.equal(new ExecutionTraceReplay(failedBundle).steps().at(-1).tone, "red");
const mixed = structuredClone(bundle);
mixed.events[0].header.run_id = "other";
assert.throws(() => new ExecutionTraceReplay(mixed), /Mixed execution runs/);
if (bundle.communication && !bundle.result.mission_kind) {
  assert.equal(bundle.communication.relay_ids.length, 2);
  assert.ok(bundle.ephemeris.samples.every(s => !s.node_id.startsWith("RELAY-")));
  assert.ok(bundle.communication.reservations.every(r => r.state === "completed"));
  let totalDelay = 0;
  for (const transfer of bundle.communication.transfers) {
    const parts = transfer.wait_s + transfer.serialization_s + transfer.acquisition_s + transfer.propagation_s;
    assert.ok(Math.abs(parts - (transfer.finish_s - transfer.requested_s)) < 1e-8);
    totalDelay += transfer.finish_s - transfer.requested_s;
    assert.ok(bundle.events.some(event => event.header.event_type === "JOB_RESTORED" &&
      Math.abs(event.header.simulation_time_ns / 1e9 - transfer.finish_s) < 1e-8));
  }
  assert.ok(Math.abs(totalDelay - bundle.result.simulated_migration_delay_s) < 1e-8);
  assert.ok(steps.filter(step => step.line.includes("LINK_RESERVATION")).every(step => step.source === "communication"));
}
if (bundle.result.mission_kind === "joint-axb") {
  assert.equal(bundle.communication.transfers.length, 2);
  assert.equal(bundle.result.transport, "tcp");
  assert.ok(!steps.some(step => step.line.includes("undefined") || step.line.includes("NaN")));
  assert.ok(steps.some(step => step.kind === "NETWORK_REPLAN"));
  assert.ok(replay.telemetryAt("sat004", 0));
  assert.ok(steps.filter(step => step.kind === "TRANSFER_COMPLETED").length === 2);
}
if (bundle.telemetry) {
  const firstNode = bundle.ephemeris.samples[0].node_id;
  const initial = replay.telemetryAt(firstNode, 0);
  const later = replay.telemetryAt(firstNode, replay.horizonS);
  assert.ok(initial && later);
  assert.equal(initial.telemetry_source, "analytic_power_thermal");
  assert.equal(initial.soc, bundle.result.initial_soc);
  assert.notEqual(initial.soc, later.soc);
  assert.notEqual(initial.temperature_c, later.temperature_c);
  assert.equal(replay.telemetryAt(firstNode, -1), null);
  assert.equal(replay.telemetryAt("unknown", replay.horizonS), null);
  assert.equal(replay.telemetryAt(firstNode, 0).soc, initial.soc);
  assert.ok(steps.every(s => s.kind !== "NODE_OPERATING_SNAPSHOT"));
}
console.log("Execution replay: trace, clock, failure and scheduler-source checks passed");

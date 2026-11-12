(() => {
  "use strict";

  class ExecutionTraceReplay {
    constructor(bundle) {
      if (bundle.schema_version !== 1 || !Array.isArray(bundle.events) || !bundle.ephemeris?.samples?.length) {
        throw new Error("Invalid execution trace");
      }
      if (bundle.events.some((event) => event.header.run_id !== bundle.run_id)) {
        throw new Error("Mixed execution runs");
      }
      this.bundle = bundle;
      this.result = bundle.result;
      this.horizonS = this.result.horizon_s;
      this.durationMs = 30000;
      this.timestamps = [...new Set(bundle.ephemeris.samples.map((sample) => sample.timestamp_ms))].sort((a, b) => a - b);
      this.epochMs = this.timestamps[0];
      this.telemetry = new Map();
      for (const event of bundle.events) {
        if (event.header.event_type !== "NODE_OPERATING_SNAPSHOT") continue;
        const node = event.header.node_id;
        if (!this.telemetry.has(node)) this.telemetry.set(node, []);
        this.telemetry.get(node).push({ ...event.payload, simS: event.header.simulation_time_ns / 1e9 });
      }
      for (const states of this.telemetry.values()) states.sort((a, b) => a.simS - b.simS);
    }

    static async load(url = "execution-trace.json") {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`Execution trace HTTP ${response.status}`);
      return new ExecutionTraceReplay(await response.json());
    }

    indexAt(simS) {
      const timestamp = this.epochMs + simS * 1000;
      let low = 0;
      let high = this.timestamps.length - 1;
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (this.timestamps[middle] <= timestamp) low = middle;
        else high = middle - 1;
      }
      return low;
    }

    steps() {
      let progress = "0%";
      return this.bundle.events.filter((event) => !["ORBIT_PROPAGATION_END", "GLOBAL_SNAPSHOT", "SIMULATION_START", "NODE_OPERATING_SNAPSHOT"].includes(event.header.event_type)).map((event) => {
        const kind = event.header.event_type;
        const payload = event.payload;
        const simS = event.header.simulation_time_ns / 1e9;
        const node = event.header.node_id;
        const failed = kind === "JOB_FAILED" || (kind === "SIMULATION_END" && !this.result.converged);
        const scheduler = event.source === "O-SLURM" && kind === "SCHEDULER_DECISION";
        const orbital = event.source === "GMAT";
        let line = `${kind}${node ? ` ${node}` : ""}`;
        if (kind === "JOB_PROGRESS") {
          progress = `${Math.min(99, Math.round(payload.iteration / Math.max(1, this.result.iteration) * 100))}%`;
          line += ` iter=${payload.iteration} residual=${Number(payload.relative_residual).toExponential(3)}`;
        }
        if (kind === "SCHEDULER_DECISION") line += ` ${payload.trigger} -> ${payload.selected_action.node_id}`;
        if (payload.slurm_job_id) line += ` slurm_job=${payload.slurm_job_id}`;
        if (payload.transfer_id) line += ` ${payload.transfer_id}`;
        if (kind === "TRANSFER_PLANNED") line += ` bytes=${payload.bytes} ready=T+${Number(payload.predicted_finish_s).toFixed(3)}s`;
        if (kind === "LINK_RESERVATION_COMMITTED") line += ` ${payload.reservation_id} ${payload.source}>${payload.destination}`;
        if (kind === "JOB_COMPLETED") {
          progress = "100%";
          line += ` residual=${Number(payload.relative_residual).toExponential(3)}`;
        }
        if (kind === "JOB_FAILED") line += ` ${payload.reason || "iteration budget exhausted"}`;
        return {
          dt: simS / this.horizonS * this.durationMs,
          simS, index: this.indexAt(simS), focus: node, progress,
          tone: failed || kind === "TRANSFER_FAILED" ? "red" : orbital && kind === "ECLIPSE_ENTRY" ? "amber" : scheduler ? "blue" : "green",
          source: scheduler ? "scheduler" : orbital ? "orbital" : event.source === "GMAT-Comm" ? "communication" : kind === "JOB_PROGRESS" ? "compute" : "execution",
          line, kind, previousNode: payload.previous_node
        };
      });
    }

    telemetryAt(node, simS) {
      const states = this.telemetry.get(node) || [];
      let low = 0, high = states.length;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (states[middle].simS <= simS) low = middle + 1;
        else high = middle;
      }
      return states[low - 1] || null;
    }
  }

  if (typeof module !== "undefined") module.exports = { ExecutionTraceReplay };
  else window.ExecutionTraceReplay = ExecutionTraceReplay;
})();

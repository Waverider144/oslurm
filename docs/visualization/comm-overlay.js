(() => {
  "use strict";

  class CommunicationTraceStore {
    constructor(url = "comm-trace.json") {
      this.url = url;
      this.trace = null;
    }

    async load() {
      try {
        const response = await fetch(this.url, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        this.trace = await response.json();
      } catch {
        this.trace = this.fallbackTrace();
      }
      return this.trace;
    }

    fallbackTrace() {
      return {
        job_id: "JOB001",
        selected_compute: "compute:SAT003",
        planner: "joint compute/network",
        visibility_fidelity: "ellipsoid:wgs84",
        transfers: [
          {
            transfer_id: "JOB001-INPUT-compute:SAT003",
            path_kind: "temporal-store-carry-forward",
            finish_s: 47.68,
            bytes: 24000000,
            hops: [
              { source: "ground:MISSION-CONTROL", destination: "comm:RELAY-A", contact_id: "GROUND-RELAY-A", start_s: 0.0, end_s: 6.4 },
              { source: "comm:RELAY-A", destination: "compute:SAT003", contact_id: "RELAY-A-SAT003", start_s: 40.0, end_s: 47.68 }
            ]
          },
          {
            transfer_id: "JOB001-RESULT-compute:SAT003",
            path_kind: "temporal-store-carry-forward",
            finish_s: 277.133,
            bytes: 8000000,
            hops: [
              { source: "compute:SAT003", destination: "comm:RELAY-A", contact_id: "SAT003-RELAY-A", start_s: 270.0, end_s: 272.56 },
              { source: "comm:RELAY-A", destination: "ground:MISSION-CONTROL", contact_id: "RELAY-A-GROUND", start_s: 275.0, end_s: 277.133 }
            ]
          }
        ],
        decision: {
          candidates: [
            { node_id: "compute:SAT001", compute_time_s: 120, network: "direct slow access", feasible: true },
            { node_id: "compute:SAT003", compute_time_s: 220, network: "relay assisted", feasible: true }
          ],
          rationale: "SAT003 wins on end-to-end finish time because relay throughput dominates local compute speed."
        }
      };
    }
  }

  class CommunicationNodeProjector {
    constructor() {
      this.sampleFor = null;
      this.kmVec = null;
      this.project = null;
    }

    bind(context) {
      this.sampleFor = context.sampleFor;
      this.kmVec = context.kmVec;
      this.project = context.project;
      if (context.communication) {
        this.relaySamples = new Map();
        for (const sample of context.communication.ephemeris.samples) {
          if (!this.relaySamples.has(sample.node_id)) this.relaySamples.set(sample.node_id, []);
          this.relaySamples.get(sample.node_id).push(sample);
        }
        for (const samples of this.relaySamples.values()) samples.sort((a, b) => a.timestamp_ms - b.timestamp_ms);
      }
    }

    pointFor(nodeId, context, index = null) {
      const relay = this.relaySamples?.get(nodeId.replace("comm:", ""));
      if (relay?.length) {
        const sample = relay[Math.min(relay.length - 1, index === null ? context.activeIndex || 0 : index)];
        return this.project(this.kmVec(sample).r, context.scale, context.cx, context.cy);
      }
      const normalized = this.normalizeComputeNode(nodeId);
      if (this.sampleFor && this.kmVec && this.project) {
        const sample = index === null ? this.sampleFor(normalized) : this.sampleFor(normalized, index);
        if (sample) return this.project(this.kmVec(sample).r, context.scale, context.cx, context.cy);
      }
      const synthetic = this.syntheticPositionKm(nodeId, index);
      return this.project(synthetic, context.scale, context.cx, context.cy);
    }

    normalizeComputeNode(nodeId) {
      if (!nodeId.startsWith("compute:")) return nodeId;
      return nodeId.split(":")[1].toLowerCase();
    }

    syntheticPositionKm(nodeId, index = null) {
      const earth = this.lastEarth || { equatorialRadiusKm: 6378.137, polarRadiusKm: 6356.752314245 };
      if (nodeId.startsWith("ground:")) return [0, earth.equatorialRadiusKm, 0];
      if (nodeId.includes("RELAY-A") && this.sampleFor && this.kmVec) {
        const sat3 = index === null ? this.sampleFor("sat003") : this.sampleFor("sat003", index);
        if (sat3) {
          const r = this.kmVec(sat3).r;
          const norm = Math.hypot(r[0], r[1], r[2]) || 1;
          const radial = r.map((value) => value / norm);
          const tangentNorm = Math.hypot(-radial[1], radial[0]) || 1;
          const tangent = [-radial[1] / tangentNorm, radial[0] / tangentNorm, 0];
          const relayRadius = norm + 1800;
          return radial.map((value, index) => value * relayRadius + tangent[index] * 1600);
        }
      }
      if (nodeId.includes("RELAY-B") && this.sampleFor && this.kmVec) {
        const sat1 = index === null ? this.sampleFor("sat001") : this.sampleFor("sat001", index);
        if (sat1) {
          const r = this.kmVec(sat1).r;
          const norm = Math.hypot(r[0], r[1], r[2]) || 1;
          const radial = r.map((value) => value / norm);
          const tangentNorm = Math.hypot(-radial[1], radial[0]) || 1;
          const tangent = [radial[1] / tangentNorm, -radial[0] / tangentNorm, 0];
          const relayRadius = norm + 2200;
          return radial.map((value, axis) => value * relayRadius + tangent[axis] * 1900 + (axis === 2 ? 850 : 0));
        }
      }
      if (nodeId.includes("RELAY-A")) return [2500, 7900, 1800];
      if (nodeId.includes("RELAY-B")) return [-4300, 6800, 2200];
      return [7600, 1200, 700];
    }

    setEarthModel(earth) {
      this.lastEarth = earth;
    }
  }

  class CommunicationOverlayRenderer {
    constructor(projector) {
      this.projector = projector;
      this.phase = 0;
    }

    draw(context, trace) {
      if (!trace || context.cameraView === "status") return;
      this.projector.setEarthModel(context.earth);
      this.phase = (context.frame || 0) * 0.025;
      context.ctx.save();
      this.drawRelayTracks(context, this.relayIds(trace));
      this.drawEndpointLabels(context, trace);
      context.ctx.restore();
    }

    relayIds(trace) {
      if (trace.communication) return trace.communication.relay_ids;
      if (trace.execution) return [];
      const ids = new Set(["comm:RELAY-A", "comm:RELAY-B"]);
      trace.transfers.forEach((transfer) => transfer.hops.forEach((hop) => {
        [hop.source, hop.destination].forEach((nodeId) => {
          if (nodeId.startsWith("comm:")) ids.add(nodeId);
        });
      }));
      return [...ids].sort();
    }

    drawRelayTracks(context, relayIds) {
      relayIds.forEach((relayId, index) => {
        this.drawRelayTrack(context, relayId, index, "back");
      });
      relayIds.forEach((relayId, index) => {
        this.drawRelayTrack(context, relayId, index, "front");
      });
    }

    drawRelayTrack(context, relayId, relayIndex, layer) {
      const sampleCount = Math.max(2, context.sampleCount || 2);
      const frontLayer = layer === "front";
      const ctx = context.ctx;
      const color = "#61d394";
      const trailLength = 7;
      const tailEnd = Math.max(0, Math.min(context.activeIndex || 0, sampleCount - 1));
      const tailStart = Math.max(0, tailEnd - trailLength);
      ctx.save();
      ctx.beginPath();
      let drawing = false;
      for (let i = tailStart; i <= tailEnd; i += 1) {
        const point = this.projector.pointFor(relayId, context, i);
        const visibleOnLayer = frontLayer ? point.z >= 0 : point.z < 0;
        if (!visibleOnLayer || (!frontLayer && this.pointOccludedByEarth(context, point))) {
          drawing = false;
          continue;
        }
        if (!drawing) {
          ctx.moveTo(point.x, point.y);
          drawing = true;
        } else {
          ctx.lineTo(point.x, point.y);
        }
      }
      ctx.strokeStyle = color;
      ctx.globalAlpha = frontLayer ? .74 : .22;
      ctx.lineWidth = frontLayer ? 1.8 : 1;
      ctx.setLineDash(frontLayer ? [] : [4, 7]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    drawHop(context, hop, transferIndex, hopIndex) {
      const from = this.projector.pointFor(hop.source, context);
      const to = this.projector.pointFor(hop.destination, context);
      if (this.pointOccludedByEarth(context, from) || this.pointOccludedByEarth(context, to)) return;
      const earthRadius = (context.earth?.equatorialRadiusKm || 6378.137) * context.scale * 1.02;
      if (this.crossesEarthDisk(from, to, context.cx, context.cy, earthRadius)) return;
      const ctx = context.ctx;
      const color = transferIndex === 0 ? "#61d394" : "#36a3ff";
      const alpha = transferIndex === 0 ? 0.72 : 0.62;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.2;
      ctx.setLineDash([10, 8]);
      ctx.lineDashOffset = -this.phase * 12 - hopIndex * 6;
      ctx.beginPath();
      this.drawOcclusionAwarePath(context, from, to, hopIndex);
      ctx.stroke();
      ctx.setLineDash([]);
      this.drawPulse(ctx, from, color, 4.5);
      this.drawPulse(ctx, to, color, 3.5);
      ctx.restore();
    }

    drawOcclusionAwarePath(context, from, to, hopIndex) {
      const ctx = context.ctx;
      const radius = (context.earth?.equatorialRadiusKm || 6378.137) * context.scale * 1.02;
      if (!this.crossesEarthDisk(from, to, context.cx, context.cy, radius)) {
        const midX = (from.x + to.x) / 2;
        const midY = (from.y + to.y) / 2 - 44 - hopIndex * 16;
        ctx.moveTo(from.x, from.y);
        ctx.quadraticCurveTo(midX, midY, to.x, to.y);
        return;
      }

      const waypoint = this.limbWaypoint(from, to, context.cx, context.cy, radius + 42 + hopIndex * 12);
      ctx.moveTo(from.x, from.y);
      ctx.quadraticCurveTo((from.x + waypoint.x) / 2, (from.y + waypoint.y) / 2, waypoint.x, waypoint.y);
      ctx.quadraticCurveTo((to.x + waypoint.x) / 2, (to.y + waypoint.y) / 2, to.x, to.y);
    }

    crossesEarthDisk(from, to, cx, cy, radius) {
      const ax = from.x - cx;
      const ay = from.y - cy;
      const bx = to.x - cx;
      const by = to.y - cy;
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      if (len2 <= 1) return false;
      const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
      const px = ax + dx * t;
      const py = ay + dy * t;
      return Math.hypot(px, py) < radius;
    }

    pointOccludedByEarth(context, point) {
      const radius = (context.earth?.equatorialRadiusKm || 6378.137) * context.scale;
      return point.z < 0 && Math.hypot(point.x - context.cx, point.y - context.cy) < radius * .99;
    }

    limbWaypoint(from, to, cx, cy, radius) {
      const midX = (from.x + to.x) / 2 - cx;
      const midY = (from.y + to.y) / 2 - cy;
      let nx = midX;
      let ny = midY;
      const len = Math.hypot(nx, ny);
      if (len < 1) {
        nx = -(to.y - from.y);
        ny = to.x - from.x;
      }
      const norm = Math.hypot(nx, ny) || 1;
      return {
        x: cx + nx / norm * radius,
        y: cy + ny / norm * radius
      };
    }

    drawPulse(ctx, point, color, radius) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, radius + Math.sin(this.phase * 2) * 1.2, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = 16;
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    drawEndpointLabels(context, trace) {
      const endpoints = new Set();
      trace.transfers.forEach((transfer) => transfer.hops.forEach((hop) => {
        endpoints.add(hop.source);
        endpoints.add(hop.destination);
      }));
      this.relayIds(trace).forEach((nodeId) => endpoints.add(nodeId));
      context.ctx.font = "800 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
      context.ctx.textBaseline = "middle";
      [...endpoints].forEach((nodeId) => {
        if (nodeId.startsWith("compute:") || /^sat\d/i.test(nodeId)) return;
        const point = this.projector.pointFor(nodeId, context);
        if (this.pointOccludedByEarth(context, point)) return;
        const isGround = nodeId.startsWith("ground:");
        const color = isGround ? "#f5b84b" : "#61d394";
        this.drawEndpointMarker(context.ctx, point, color, isGround ? "ground" : "relay");
        context.ctx.fillStyle = color;
        const label = this.shortName(nodeId);
        const x = Math.max(10, Math.min(context.width - 92, point.x + 9));
        const y = Math.max(14, Math.min(context.height - 14, point.y + 2));
        context.ctx.fillText(label, x, y);
      });
    }

    drawEndpointMarker(ctx, point, color, kind) {
      ctx.save();
      ctx.fillStyle = color;
      ctx.strokeStyle = "rgba(230, 237, 247, .72)";
      ctx.lineWidth = 1.2;
      ctx.shadowColor = color;
      ctx.shadowBlur = 14;
      ctx.beginPath();
      if (kind === "relay") {
        ctx.moveTo(point.x, point.y - 8);
        ctx.lineTo(point.x + 8, point.y + 7);
        ctx.lineTo(point.x - 8, point.y + 7);
        ctx.closePath();
      } else {
        ctx.arc(point.x, point.y, 5.5, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.stroke();
      ctx.restore();
    }

    shortName(nodeId) {
      return nodeId.replace("ground:", "").replace("comm:", "");
    }
  }

  class CommunicationPanel {
    constructor(root = document) {
      this.root = root;
      this.container = null;
    }

    mount() {
      const mount = this.root.querySelector("#commPanelMount");
      const stage = this.root.querySelector(".orbit-stage");
      const target = mount || stage;
      if (!target || this.container) return;
      this.container = document.createElement("section");
      this.container.className = mount ? "comm-panel" : "comm-panel earth-only floating";
      this.container.innerHTML = `
        <div class="comm-panel-head">
          <span>Comm Co-Scheduler</span>
          <strong id="commSelected">pending</strong>
        </div>
        <div class="comm-fidelity" id="commFidelity">visibility pending</div>
        <div class="comm-transfer-list" id="commTransfers"></div>
      `;
      target.appendChild(this.container);
      this.injectStyles();
      this.bindViewState();
    }

    update(trace, simS = 0) {
      this.mount();
      const selected = this.root.querySelector("#commSelected");
      const fidelity = this.root.querySelector("#commFidelity");
      const list = this.root.querySelector("#commTransfers");
      if (!selected || !list || !trace) return;
      selected.textContent = trace.selected_compute || "n/a";
      if (fidelity) fidelity.textContent = `visibility ${trace.visibility_fidelity || "ellipsoid:wgs84"}`;
      if (trace.communication) {
        const transfers = trace.transfers;
        const inFlight = transfers.find((transfer) => transfer.requested_s <= simS && simS < transfer.finish_s);
        const active = transfers.flatMap((transfer) => transfer.hops).filter((hop) => hop.start_s <= simS && simS < hop.end_s).length;
        const reserved = transfers.filter((transfer) => transfer.requested_s <= simS && simS < transfer.finish_s).reduce((count, transfer) => count + transfer.hops.length, 0);
        selected.textContent = inFlight ? `${inFlight.hops[0].source} > ${inFlight.hops.at(-1).destination}` : trace.communication.kind || "Checkpoint network";
        fidelity.textContent = `${reserved} reserved / ${active} active / WGS84`;
        const status = this.root.querySelector("#commStatus");
        if (status) status.textContent = !transfers.length ? "idle" : inFlight ? "active" : simS >= Math.max(...transfers.map(t => t.finish_s)) ? "complete" : "ready";
        list.replaceChildren();
        for (const transfer of transfers) {
          const article = document.createElement("article");
          article.className = "comm-transfer";
          article.dataset.transferId = transfer.transfer_id;
          const title = document.createElement("span");
          title.textContent = transfer.transfer_id;
          const state = document.createElement("b");
          state.textContent = simS < transfer.requested_s ? "queued" : simS >= transfer.finish_s ? "delivered" : transfer.hops.some(h => h.start_s <= simS && simS < h.end_s) ? "transferring" : "waiting";
          const timing = document.createElement("small");
          timing.textContent = `${this.formatBytes(transfer.bytes)} / ${(transfer.finish_s - transfer.requested_s).toFixed(2)}s / T+${transfer.finish_s.toFixed(2)}`;
          article.append(title, state, timing);
          list.append(article);
        }
        return;
      }
      if (trace.execution) {
        const status = this.root.querySelector("#commStatus");
        if (status) status.textContent = "idle";
        fidelity.textContent = "Shared checkpoint storage";
        list.textContent = "Radio transfer not scheduled";
        return;
      }
      list.innerHTML = trace.transfers.map((transfer) => `
        <article class="comm-transfer">
          <span>${transfer.transfer_id}</span>
          <b>${transfer.path_kind}</b>
          <small>${this.formatBytes(transfer.bytes)} / finish T+${Number(transfer.finish_s).toFixed(1)}s</small>
        </article>
      `).join("");
    }

    formatBytes(bytes) {
      if (bytes >= 1000000) return `${(bytes / 1000000).toFixed(1)} MB`;
      if (bytes >= 1000) return `${(bytes / 1000).toFixed(1)} KB`;
      return `${bytes} B`;
    }

    injectStyles() {
      if (this.root.querySelector("#commOverlayStyles")) return;
      const style = document.createElement("style");
      style.id = "commOverlayStyles";
      style.textContent = `
        .comm-panel {
          width: 100%;
          padding: 10px;
          border: 1px solid rgba(97, 211, 148, .34);
          border-radius: 6px;
          background: rgba(6, 9, 17, .78);
          backdrop-filter: blur(8px);
          display: grid;
          gap: 9px;
          z-index: 4;
        }
        .comm-panel.floating {
          position: absolute;
          right: 14px;
          top: 14px;
          width: min(310px, calc(100% - 28px));
        }
        .comm-panel-head {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          color: var(--muted);
          font-size: .68rem;
          font-weight: 900;
          text-transform: uppercase;
        }
        .comm-panel-head strong {
          color: var(--green);
          font: 900 .68rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .comm-transfer-list {
          display: grid;
          gap: 6px;
        }
        .comm-fidelity {
          color: var(--muted);
          font: 800 .62rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          text-transform: uppercase;
        }
        .comm-transfer {
          min-height: 48px;
          padding: 8px;
          border: 1px solid rgba(143, 162, 184, .18);
          border-left: 3px solid var(--green);
          border-radius: 5px;
          background: rgba(12, 18, 28, .76);
          display: grid;
          gap: 3px;
        }
        .comm-transfer span {
          color: var(--text);
          font: 800 .66rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .comm-transfer b,
        .comm-transfer small {
          color: var(--muted);
          font-size: .63rem;
          font-weight: 800;
          text-transform: uppercase;
        }
        @media (max-width: 1100px) {
          .comm-panel.floating { top: 60px; }
        }
      `;
      document.head.appendChild(style);
    }

    bindViewState() {
      this.root.querySelectorAll("[data-view]").forEach((button) => {
        button.addEventListener("click", () => {
          if (!this.container || !this.container.classList.contains("floating")) return;
          this.container.classList.toggle("hidden", button.dataset.view === "status");
        });
      });
    }
  }

  class CommunicationVisualization {
    constructor(root = document) {
      this.root = root;
      this.store = new CommunicationTraceStore();
      this.projector = new CommunicationNodeProjector();
      this.renderer = new CommunicationOverlayRenderer(this.projector);
      this.panel = new CommunicationPanel(root);
      this.trace = null;
    }

    async start() {
      this.panel.mount();
      window.addEventListener("oslurm:ephemeris-loaded", (event) => {
        this.projector.bind(event.detail);
        this.projector.setEarthModel(event.detail.earth);
        if (event.detail.execution) {
          const communication = event.detail.communication;
          this.trace = { execution: event.detail.execution, communication,
            transfers: communication?.transfers || [], relay_ids: communication?.relay_ids || [], selected_compute: "Not scheduled" };
          this.panel.update(this.trace);
        }
      });
      window.addEventListener("oslurm:orbit-render", (event) => {
        if (event.detail.cameraView === "map") {
          if (this.trace?.communication) this.panel.update(this.trace, event.detail.simulationTimeS || 0);
          return;
        }
        this.projector.bind(event.detail);
        this.renderer.draw(event.detail, this.trace);
        if (this.trace?.communication) this.panel.update(this.trace, event.detail.simulationTimeS || 0);
      });
      const stored = await this.store.load();
      if (!this.trace?.execution) this.trace = stored;
      this.panel.update(this.trace);
    }
  }

  window.CommunicationVisualization = CommunicationVisualization;
  window.addEventListener("DOMContentLoaded", () => new CommunicationVisualization().start());
})();

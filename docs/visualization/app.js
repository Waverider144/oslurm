(() => {
  "use strict";

  class MissionControlApp {
    constructor(root = document) {
      this.root = root;
    }

    start() {
          const root = this.root;
          const MU = 398600.4418;
          const EARTH_EQUATORIAL_RADIUS_KM = 6378.137;
          const EARTH_POLAR_RADIUS_KM = 6356.752314245;
          const COLORS = {
            blue: "#36a3ff",
            amber: "#f5b84b",
            red: "#ff4d5c",
            green: "#61d394",
            muted: "#8fa2b8",
            text: "#e6edf7"
          };
      
          const fallbackEphemeris = {
            samples: [
              { node_id: "sat001", timestamp_ms: 0, position_eci_m: [-1201819, 6811702, 237869], velocity_eci_mps: [-7473, -1317, -45], in_sunlight: true },
              { node_id: "sat002", timestamp_ms: 0, position_eci_m: [-6815854, -1201086, -41942], velocity_eci_mps: [1317, -7469, -260], in_sunlight: false },
              { node_id: "sat003", timestamp_ms: 0, position_eci_m: [1201819, -6811702, -237869], velocity_eci_mps: [7473, 1317, 45], in_sunlight: true },
              { node_id: "sat004", timestamp_ms: 0, position_eci_m: [6815854, 1201086, 41942], velocity_eci_mps: [-1317, 7469, 260], in_sunlight: true }
            ],
            events: []
          };
      
          const canvas = this.root.querySelector("#orbitCanvas");
          const ctx = canvas.getContext("2d");
          const eventList = this.root.querySelector("#eventList");
          const clock = this.root.querySelector("#clock");
          const loopStatus = this.root.querySelector("#loopStatus");
          const jobTitle = this.root.querySelector("#jobTitle");
          const jobMeta = this.root.querySelector("#jobMeta");
          const jobProgress = this.root.querySelector("#jobProgress");
          const satelliteSelect = this.root.querySelector("#satelliteSelect");
          const orbitalGrid = this.root.querySelector("#orbitalGrid");
          const nodeCards = this.root.querySelector("#nodeCards");
          const dataSource = this.root.querySelector("#dataSource");
          const viewButtons = this.root.querySelectorAll("[data-view]");
          const statusBoard = this.root.querySelector("#statusBoard");
          const earthOnlyElements = this.root.querySelectorAll(".earth-only");
          const gridToggle = this.root.querySelector("#gridToggle");
          const pointerModeButtons = this.root.querySelectorAll("[data-pointer-mode]");
          const pointerHint = this.root.querySelector("#pointerHint");
          const eventFilters = this.root.querySelectorAll(".event-filter input");
          const commandInput = this.root.querySelector("#commandInput");
          const commandOutput = this.root.querySelector("#commandOutput");
          const commandState = this.root.querySelector("#commandState");
          const sendCommand = this.root.querySelector("#sendCommand");
          const resetCommand = this.root.querySelector("#resetCommand");
          const schedulerTarget = this.root.querySelector("#schedulerTarget");
          const schedulerState = this.root.querySelector("#schedulerState");
      
          let ephemeris = fallbackEphemeris;
          let executionReplay = null;
          let byNode = new Map();
          let nodes = [];
          let selectedNode = "sat001";
          let activeIndex = 0;
          let simulationTimeS = 0;
          let inspectorIndex = 0;
          let activeTone = new Map([["sat001", "blue"]]);
          let statusMode = "sat";
          let cameraView = "iso";
          let viewPan = { x: 0, y: 0 };
          let viewZoom = 1;
          let viewAngles = { yaw: 0.72, pitch: -0.55 };
          let pointerMode = "rotate";
          let gridEnabled = true;
          let dragState = null;
          let eventStore = [];
          let earthTextureData = null;
          let renderFrame = 0;
          const groundTrack = new window.GroundTrackView(() => render());
      
          function kmVec(sample) {
            return {
              r: sample.position_eci_m.map((v) => v / 1000),
              v: sample.velocity_eci_mps.map((v) => v / 1000)
            };
          }
      
          function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
          function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
          function norm(a) { return Math.sqrt(dot(a, a)); }
          function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
          function deg(rad) { return rad * 180 / Math.PI; }
          function geocentricLat(point) { return Math.asin(clamp(point[2] / Math.max(1e-9, norm(point)), -1, 1)); }
          function earthRadiusAtGeocentricLat(lat) {
            const a = EARTH_EQUATORIAL_RADIUS_KM;
            const b = EARTH_POLAR_RADIUS_KM;
            const c = Math.cos(lat);
            const s = Math.sin(lat);
            return 1 / Math.sqrt((c * c) / (a * a) + (s * s) / (b * b));
          }
      
          function orbitalElements(sample) {
            const { r, v } = kmVec(sample);
            const rmag = norm(r);
            const vmag = norm(v);
            const h = cross(r, v);
            const hmag = norm(h);
            const n = cross([0, 0, 1], h);
            const nmag = norm(n);
            const evec = cross(v, h).map((x, i) => x / MU - r[i] / rmag);
            const ecc = norm(evec);
            const energy = vmag * vmag / 2 - MU / rmag;
            const a = -MU / (2 * energy);
            const inc = Math.acos(clamp(h[2] / hmag, -1, 1));
            let raan = nmag > 1e-8 ? Math.acos(clamp(n[0] / nmag, -1, 1)) : 0;
            if (n[1] < 0) raan = 2 * Math.PI - raan;
            let argp = nmag > 1e-8 && ecc > 1e-8 ? Math.acos(clamp(dot(n, evec) / (nmag * ecc), -1, 1)) : 0;
            if (evec[2] < 0) argp = 2 * Math.PI - argp;
            let nu = ecc > 1e-8 ? Math.acos(clamp(dot(evec, r) / (ecc * rmag), -1, 1)) : 0;
            if (dot(r, v) < 0) nu = 2 * Math.PI - nu;
            return {
              a, ecc, inc: deg(inc), raan: deg(raan), argp: deg(argp), nu: deg(nu),
              altitude: rmag - earthRadiusAtGeocentricLat(geocentricLat(r)),
              speed: vmag,
              sunlight: sample.in_sunlight
            };
          }

          function orbitPeriodSeconds(node = selectedNode) {
            const sample = sampleFor(node, 0);
            if (!sample) return 5700;
            const elements = orbitalElements(sample);
            return Math.round(2 * Math.PI * Math.sqrt(Math.pow(elements.a, 3) / MU));
          }
      
          function fmt(value, unit = "", digits = 2) {
            if (!Number.isFinite(value)) return "n/a";
            return `${value.toFixed(digits)}${unit}`;
          }
      
          function groupSamples(data) {
            byNode = new Map();
            data.samples.forEach((sample) => {
              if (!byNode.has(sample.node_id)) byNode.set(sample.node_id, []);
              byNode.get(sample.node_id).push(sample);
            });
            byNode.forEach((samples) => samples.sort((a, b) => a.timestamp_ms - b.timestamp_ms));
            nodes = [...byNode.keys()].sort();
            selectedNode = nodes.includes(selectedNode) ? selectedNode : nodes[0];
          }
      
          function sampleFor(node, index = activeIndex) {
            const samples = byNode.get(node) || [];
            return samples[Math.min(index, samples.length - 1)] || samples[0];
          }
      
          function sampleAtIndex(index = activeIndex) {
            return sampleFor(selectedNode, index) || ephemeris.samples?.[0];
          }
      
          function formatElapsed(seconds) {
            return `T+${String(Math.max(0, Math.round(seconds))).padStart(3, "0")}s`;
          }
      
          function utcForIndex(index = activeIndex) {
            const sample = sampleAtIndex(index);
            return sample ? new Date(sample.timestamp_ms).toISOString().replace(".000Z", "Z") : "UTC unavailable";
          }
      
          function utcForElapsed(seconds) {
            const epoch = ephemeris.samples?.[0]?.timestamp_ms || sampleAtIndex()?.timestamp_ms || Date.now();
            return new Date(epoch + Math.max(0, Math.round(seconds)) * 1000).toISOString().replace(".000Z", "Z");
          }
      
          function setClock(elapsedSeconds = null) {
            simulationTimeS = elapsedSeconds === null ? (sampleAtIndex().timestamp_ms - ephemeris.samples[0].timestamp_ms) / 1000 : elapsedSeconds;
            clock.textContent = elapsedSeconds === null ? utcForIndex(activeIndex) : utcForElapsed(elapsedSeconds);
            updateTelemetryCards();
            const autonomy = executionReplay?.result.autonomy;
            if (autonomy) {
              root.querySelector("#groundStatus").textContent = simulationTimeS >= autonomy.ground_disconnect_s ? "disconnected" : "connected";
              root.querySelector("#schedulerConstraint").textContent = simulationTimeS > autonomy.authority_until_s ? "lease expired" : `lease T+${autonomy.authority_until_s}s`;
            }
          }
      
          function updateInspector() {
            const sample = sampleFor(selectedNode, inspectorIndex);
            if (!sample) return;
            const el = orbitalElements(sample);
            const rows = [
              ["Semi-major axis", fmt(el.a, " km", 1)],
              ["Eccentricity", fmt(el.ecc, "", 5)],
              ["Inclination", fmt(el.inc, " deg", 2)],
              ["RAAN", fmt(el.raan, " deg", 2)],
              ["Arg. periapsis", fmt(el.argp, " deg", 2)],
              ["True anomaly", fmt(el.nu, " deg", 2)],
              ["Altitude", fmt(el.altitude, " km", 1)],
              ["Speed", fmt(el.speed, " km/s", 3)],
              ["Earth model", "WGS84 ellipsoid"],
              ["Sunlight", el.sunlight ? "YES" : "NO"],
              ["ECI sample", `#${inspectorIndex}`]
            ];
            orbitalGrid.innerHTML = rows.map(([k, v]) => `<div class="kv"><span>${k}</span><strong>${v}</strong></div>`).join("");
            updateCommandTemplate();
          }
      
          function slurmTemplate(node) {
            if (!executionReplay) return "";
            const result = executionReplay.result;
            return [
              "#!/usr/bin/env bash",
              `# run_id=${result.run_id}`,
              `# GMAT=${result.gmat_backend} execution=${result.execution_backend}`,
              `# horizon=${result.horizon_s}s; iterations/sim-second=${result.iterations_per_sim_s}`,
              `#SBATCH --job-name=${result.job_id}`,
              "python3 -m oslurm.orbit_benchmark \\",
              `  --backend ${result.execution_backend} --dimension ${result.dimension} \\`,
              `  --iteration-rate ${result.iterations_per_sim_s} --policy ${result.policy} \\`,
              `  --eclipse-factor ${result.eclipse_throughput_factor} --seed ${result.seed} --tolerance ${result.tolerance} \\`,
              `  --checkpoint-transport ${result.checkpoint_transport || "shared"} --comm-bandwidth-mbps ${result.comm_bandwidth_mbps || 8} \\`,
              `  --comm-max-range-m ${result.comm_max_range_m || 80000000} --relay-buffer-mb ${result.relay_buffer_mb ?? 64} \\`,
              `  --initial-soc ${result.initial_soc ?? 0.42} --initial-temperature-c ${result.initial_temperature_c ?? 42} \\`,
              `  --ground-disconnect-s ${result.autonomy?.ground_disconnect_s ?? 240}${result.autonomy ? ` --authority-until-s ${result.autonomy.authority_until_s}` : ""} --publish`
            ].join("\n");
          }
      
          function updateCommandTemplate(force = false) {
            if (!commandInput || !selectedNode) return;
            const currentNodeLine = commandInput.value.match(/^export OSLURM_NODE=(.+)$/m);
            const currentNode = currentNodeLine ? currentNodeLine[1].trim() : "";
            if (force || !commandInput.value.trim() || currentNode !== selectedNode) {
              commandInput.value = slurmTemplate(selectedNode);
            }
            updateJobStrip();
          }
      
          function parseDirective(text, name) {
            const match = text.match(new RegExp(`^#SBATCH\\s+--${name}=([^\\n]+)`, "m"));
            return match ? match[1].trim() : "";
          }
      
          function parseEnv(text, name) {
            const match = text.match(new RegExp(`^export\\s+${name}=([^\\n]+)`, "m"));
            return match ? match[1].replace(/^["']|["']$/g, "").trim() : "";
          }

          function gmatSatelliteCount() {
            return nodes.length || 0;
          }

          function commandJobName() {
            return parseDirective(commandInput.value, "job-name") || `oslurm-${selectedNode}-orbit-profile-axb`;
          }

          function updateJobStrip(jobName = commandJobName()) {
            const count = gmatSatelliteCount();
            jobTitle.textContent = executionReplay ? `Ax=b ON ${count} SATELLITES` : `PARALLELISM ON ${count} SATELLITES`;
            jobMeta.textContent = `${jobName} / ${count} GMAT satellites`;
          }
      
          function expandNodeList(value) {
            const compact = value.match(/^(.*)\[(\d+)-(\d+)\]$/);
            if (!compact) return value.split(",").map((node) => node.trim()).filter(Boolean);
            const [, prefix, start, end] = compact;
            const width = start.length;
            const first = Number(start);
            const last = Number(end);
            const expanded = [];
            for (let i = first; i <= last; i += 1) expanded.push(`${prefix}${String(i).padStart(width, "0")}`);
            return expanded;
          }
      
          let commandTimers = [];
          let commandOrbitTimer = null;
      
          function clearCommandTimers() {
            commandTimers.forEach((timer) => window.clearTimeout(timer));
            commandTimers = [];
            stopCommandOrbitReplay();
            sendCommand.disabled = !executionReplay;
          }

          function stopCommandOrbitReplay() {
            if (!commandOrbitTimer) return;
            window.clearInterval(commandOrbitTimer);
            commandOrbitTimer = null;
          }

          function startCommandOrbitReplay(durationMs, sampleCount) {
            stopCommandOrbitReplay();
            const startedAt = performance.now();
            commandOrbitTimer = window.setInterval(() => {
              const ratio = Math.max(0, Math.min(1, (performance.now() - startedAt) / Math.max(1, durationMs)));
              const simS = ratio * executionReplay.horizonS;
              activeIndex = executionReplay.indexAt(simS);
              setClock(simS);
              render();
            }, 320);
          }
      
          function appendOutput(line) {
            commandOutput.textContent += `${line}\n`;
            commandOutput.scrollTop = commandOutput.scrollHeight;
          }
      
          function runCommandSimulation() {
            clearCommandTimers();
            if (!executionReplay) {
              appendOutput("No execution trace available.");
              commandState.textContent = "unavailable";
              return;
            }
            const replay = executionReplay.steps();
            commandOutput.textContent = "";
            commandState.textContent = "replaying";
            sendCommand.disabled = true;
            loopStatus.textContent = "Replay";
            updateJobStrip(commandJobName());
            jobProgress.style.width = "0%";
            eventStore = [];
            renderEvents();
            const sampleCount = Math.max(1, ...nodes.map((node) => (byNode.get(node) || []).length));
            const replayDurationMs = executionReplay.durationMs;
            startCommandOrbitReplay(replayDurationMs, sampleCount);
            addEventDivider(`START UTC ${utcForElapsed(0)}`);
            appendOutput(`run=${executionReplay.bundle.run_id} backend=${executionReplay.result.execution_backend}`);
            replay.forEach((step, idx) => {
              const timer = window.setTimeout(() => {
                const elapsedS = Number.isFinite(step.simS) ? step.simS : step.dt / 100;
                if (step.progress) jobProgress.style.width = step.progress;
                const orbitIndex = Number.isInteger(step.index)
                  ? step.index
                  : executionReplay.indexAt(elapsedS);
                activeIndex = Math.max(0, Math.min(sampleCount - 1, orbitIndex));
                setClock(elapsedS);
                if (step.focus) {
                  const labels = { JOB_PROGRESS: "solve", JOB_STARTED: "solve", JOB_RESTORED: "solve", JOB_CHECKPOINT_END: "saved", JOB_COMPLETED: "done", JOB_FAILED: "failed", ECLIPSE_ENTRY: "eclipse", ECLIPSE_EXIT: "sunlit" };
                  if (labels[step.kind]) setNodeTone(step.focus, step.tone, labels[step.kind]);
                }
                if (step.kind === "SCHEDULER_DECISION") {
                  schedulerTarget.textContent = step.focus;
                  schedulerState.textContent = "active";
                  if (step.previousNode) setNodeTone(step.previousNode, "green", "idle");
                }
                appendOutput(step.line);
                addEvent({ t: formatElapsed(elapsedS), tone: step.tone, source: step.source, text: step.line });
                render();
                if (idx === replay.length - 1) {
                  commandState.textContent = executionReplay.result.converged ? "complete" : "failed";
                  loopStatus.textContent = executionReplay.result.converged ? "Pass" : "Fail";
                  schedulerState.textContent = executionReplay.result.converged ? "complete" : "failed";
                  stopCommandOrbitReplay();
                  addEventDivider(`END UTC ${utcForElapsed(elapsedS)}`);
                  sendCommand.disabled = false;
                  commandTimers = [];
                }
              }, step.dt);
              commandTimers.push(timer);
            });
          }
      
          function setupControls() {
            satelliteSelect.innerHTML = nodes.map((node) => `<option value="${node}">${node}</option>`).join("");
            satelliteSelect.value = selectedNode;
            satelliteSelect.addEventListener("change", () => {
              selectedNode = satelliteSelect.value;
              updateInspector();
              updateCommandTemplate(true);
              render();
            });
            viewButtons.forEach((button) => {
              button.addEventListener("click", () => {
                cameraView = button.dataset.view;
                canvas.setAttribute("aria-label", cameraView === "map" ? "Earth ground track map" : "3D Earth and GMAT orbit visualization");
                applyPresetView(cameraView);
                viewButtons.forEach((b) => b.classList.toggle("active", b === button));
                pointerModeButtons.forEach(b => { b.disabled = cameraView === "map" && b.dataset.pointerMode === "rotate"; });
                if (cameraView === "map") {
                  pointerMode = "pan";
                  pointerModeButtons.forEach(b => b.classList.toggle("active", b.dataset.pointerMode === pointerMode));
                  updatePointerHint();
                }
                render();
              });
            });
            eventFilters.forEach((filter) => filter.addEventListener("change", renderEvents));
            gridToggle.addEventListener("click", () => {
              gridEnabled = !gridEnabled;
              gridToggle.classList.toggle("active", gridEnabled);
              render();
            });
            pointerModeButtons.forEach((button) => {
              button.addEventListener("click", () => {
                pointerMode = button.dataset.pointerMode;
                pointerModeButtons.forEach((btn) => btn.classList.toggle("active", btn === button));
                updatePointerHint();
              });
            });
          }
      
          function applyPresetView(view) {
            if (view === "iso") viewAngles = { yaw: 0.72, pitch: -0.55 };
            if (view === "eci") viewAngles = { yaw: 0.00, pitch: -0.18 };
          }
      
          function updatePointerHint() {
            const labels = {
              rotate: "left drag rotate / ctrl drag pan / wheel zoom",
              pan: "left drag pan / wheel zoom",
              select: "left click select satellite / ctrl drag pan / wheel zoom"
            };
            pointerHint.textContent = labels[pointerMode];
          }
      
          function makeNodeCards() {
            nodeCards.innerHTML = nodes.map((node) => `
              <article class="node" data-card="${node}">
                <div class="node-head"><h3>${node}</h3><span class="tag ${node === "sat001" ? "blue" : ""}">${node === "sat001" ? "alloc" : "idle"}</span></div>
                <div class="metric" data-metric="soc"><span>SoC</span><div class="bar" style="--value:0%"><span></span></div><b>--</b></div>
                <div class="metric" data-metric="thermal"><span>Thermal</span><div class="bar" style="--value:0%"><span></span></div><b>--</b></div>
              </article>
            `).join("");
            updateTelemetryCards();
            renderStatusBoard();
          }

          function updateTelemetryCards() {
            for (const card of nodeCards.querySelectorAll("[data-card]")) {
              const state = executionReplay?.telemetryAt(card.dataset.card, simulationTimeS);
              for (const key of ["soc", "thermal"]) {
                const metric = card.querySelector(`[data-metric="${key}"]`);
                const value = key === "soc" ? state?.soc : state?.temperature_c;
                const valid = Number.isFinite(value);
                metric.querySelector("b").textContent = valid ? key === "soc" ? `${(value * 100).toFixed(1)}%` : `${value.toFixed(1)} C` : "--";
                metric.dataset.value = valid ? String(value) : "";
                metric.title = state ? `${state.telemetry_source} / T+${state.simS.toFixed(1)}s` : "Telemetry unavailable";
                const bar = metric.querySelector(".bar");
                bar.style.setProperty("--value", `${valid ? clamp(key === "soc" ? value * 100 : value / (state.hard_limit_c || 80) * 100, 0, 100) : 0}%`);
                const tone = !valid ? "" : key === "soc" ? value <= state.reserve_soc ? "red" : value < state.reserve_soc + 0.05 ? "amber" : "" : value >= state.hard_limit_c ? "red" : value >= state.soft_limit_c ? "amber" : "";
                bar.className = `bar ${tone}`;
              }
            }
          }
      
          function addEvent(step) {
            if (step.source === "communication") return;
            if (step.tone === "blue" && step.source !== "scheduler") return;
            eventStore.push(step);
            renderEvents();
          }
      
          function addEventDivider(text) {
            eventStore.push({ kind: "divider", text });
            renderEvents();
          }
      
          function enabledEventTones() {
            return new Set([...eventFilters].filter((filter) => filter.checked).map((filter) => filter.value));
          }
      
          function renderEvents() {
            const enabled = enabledEventTones();
            eventList.innerHTML = "";
            [...eventStore].reverse().filter((step) => step.kind === "divider" || enabled.has(step.tone)).forEach((step) => {
              if (step.kind === "divider") {
                const divider = document.createElement("div");
                divider.className = "event-divider";
                divider.textContent = step.text;
                eventList.appendChild(divider);
                return;
              }
              const item = document.createElement("div");
              item.className = `event ${step.tone}`;
                const time = document.createElement("span");
                time.className = "time";
                time.textContent = step.t;
                const text = document.createElement("span");
                text.textContent = step.text;
                item.append(time, text);
              eventList.appendChild(item);
            });
          }
      
          function setNodeTone(node, tone, label) {
            if (!node) return;
            activeTone.set(node, tone);
            const card = nodeCards.querySelector(`[data-card="${node}"]`);
            if (card) {
              const tag = card.querySelector(".tag");
              tag.className = `tag ${tone}`;
              tag.textContent = label;
            }
            renderStatusBoard();
          }
      
          function renderStatusBoard() {
            const recordedRelays = executionReplay?.bundle.communication?.relay_ids;
            const relayItems = recordedRelays ? recordedRelays.map((id) => ({ id, tone: "green", state: "nominal" })) : executionReplay ? [] : [
              { id: "RELAY-A", tone: "green", state: "nominal" },
              { id: "RELAY-B", tone: "green", state: "nominal" }
            ];
            const tiles = statusMode === "relay"
              ? relayItems.map((relay) => `<div class="status-tile ${relay.tone}">${relay.id}<small>${relay.state}</small></div>`).join("")
              : nodes.map((node) => {
                const tone = activeTone.get(node) || "green";
                return `<div class="status-tile ${tone}">${node}<small>${tone === "green" ? "nominal" : tone}</small></div>`;
              }).join("");
            statusBoard.innerHTML = `
              <div class="status-tabs" aria-label="Status board mode">
                <button class="status-mode ${statusMode === "sat" ? "active" : ""}" data-status-mode="sat" type="button">SAT</button>
                <button class="status-mode ${statusMode === "relay" ? "active" : ""}" data-status-mode="relay" type="button">RELAY</button>
              </div>
              <div class="status-grid">${tiles}</div>
            `;
            statusBoard.querySelectorAll("[data-status-mode]").forEach((button) => {
              button.addEventListener("click", () => {
                statusMode = button.dataset.statusMode;
                renderStatusBoard();
              });
            });
          }
      
          function pickSatellite(clientX, clientY) {
            const rect = canvas.getBoundingClientRect();
            if (cameraView === "map") {
              const node = groundTrack.pick(clientX - rect.left, clientY - rect.top);
              if (node) { selectedNode = node; satelliteSelect.value = node; updateInspector(); render(); }
              return;
            }
            const w = rect.width;
            const h = rect.height;
            const cx = w * .5 + viewPan.x;
            const cy = h * .52 + viewPan.y;
            const scale = Math.min(w, h) * .34 * viewZoom / 7300;
            const x = clientX - rect.left;
            const y = clientY - rect.top;
            let nearest = null;
            nodes.forEach((node) => {
              const sample = sampleFor(node);
              if (!sample) return;
              const p = project(kmVec(sample).r, scale, cx, cy);
              const distance = Math.hypot(p.x - x, p.y - y);
              if (!nearest || distance < nearest.distance) nearest = { node, distance };
            });
            if (nearest && nearest.distance < 28) {
              selectedNode = nearest.node;
              satelliteSelect.value = selectedNode;
              updateInspector();
              render();
            }
          }
      
          function resetConsole() {
            clearCommandTimers();
            eventStore = [];
            eventList.innerHTML = "";
            commandOutput.textContent = "";
            commandState.textContent = "idle";
            schedulerState.textContent = "ready";
            schedulerTarget.textContent = "--";
            setClock(0);
            loopStatus.textContent = "Armed";
            updateJobStrip();
            jobProgress.style.width = "0%";
            activeIndex = 0;
            inspectorIndex = 0;
            activeTone = new Map([["sat001", "blue"]]);
            viewPan = { x: 0, y: 0 };
            viewZoom = 1;
            groundTrack.reset();
            applyPresetView(cameraView);
            makeNodeCards();
            updateInspector();
            updateCommandTemplate(true);
            render();
          }
      
          function resizeCanvas() {
            const rect = canvas.getBoundingClientRect();
            const scale = window.devicePixelRatio || 1;
            const width = Math.max(1, Math.floor(rect.width * scale));
            const height = Math.max(1, Math.floor(rect.height * scale));
            if (canvas.width !== width) canvas.width = width;
            if (canvas.height !== height) canvas.height = height;
            ctx.setTransform(scale, 0, 0, scale, 0, 0);
          }
      
          function rotate(point) {
            const [x, y, z] = point;
            const ax = viewAngles.pitch;
            const ay = viewAngles.yaw;
            const az = cameraView === "eci" ? 0 : 0.18;
            const cx = Math.cos(ax), sx = Math.sin(ax);
            const cy = Math.cos(ay), sy = Math.sin(ay);
            const cz = Math.cos(az), sz = Math.sin(az);
            let py = y * cx - z * sx, pz = y * sx + z * cx, px = x;
            let qx = px * cy + pz * sy, qz = -px * sy + pz * cy, qy = py;
            return [qx * cz - qy * sz, qx * sz + qy * cz, qz];
          }
      
          function inverseRotate(point) {
            let [x, y, z] = point;
            const ax = -viewAngles.pitch;
            const ay = -viewAngles.yaw;
            const az = cameraView === "eci" ? 0 : -0.18;
            const cz = Math.cos(az), sz = Math.sin(az);
            let px = x * cz - y * sz;
            let py = x * sz + y * cz;
            let pz = z;
            const cy = Math.cos(ay), sy = Math.sin(ay);
            const qx = px * cy + pz * sy;
            const qz = -px * sy + pz * cy;
            const qy = py;
            const cx = Math.cos(ax), sx = Math.sin(ax);
            return [qx, qy * cx - qz * sx, qy * sx + qz * cx];
          }
      
          function loadEarthTexture() {
            const image = new Image();
            image.onload = () => {
              const textureCanvas = document.createElement("canvas");
              textureCanvas.width = image.naturalWidth;
              textureCanvas.height = image.naturalHeight;
              const textureCtx = textureCanvas.getContext("2d");
              textureCtx.drawImage(image, 0, 0);
              earthTextureData = textureCtx.getImageData(0, 0, textureCanvas.width, textureCanvas.height);
              render();
            };
            image.src = "earth-blue-marble.jpg";
          }
      
          function sampleEarthTexture(lon, lat) {
            if (!earthTextureData) return [36, 91, 122];
            const { width, height, data } = earthTextureData;
            const u = ((lon + Math.PI) / (Math.PI * 2) * width + width) % width;
            const v = clamp((Math.PI / 2 - lat) / Math.PI * height, 0, height - 1);
            const x = Math.floor(u);
            const y = Math.floor(v);
            const idx = (y * width + x) * 4;
            return [data[idx], data[idx + 1], data[idx + 2]];
          }
      
          function project(point, scale, cx, cy) {
            const [x, y, z] = rotate(point);
            return { x: cx + x * scale, y: cy - y * scale, z, perspective: 1 };
          }
      
          function projectRotated(rotated, scale, cx, cy) {
            const [x, y, z] = rotated;
            return { x: cx + x * scale, y: cy - y * scale, z, perspective: 1 };
          }
      
          function earthPoint(lonDeg, latDeg) {
            const lon = lonDeg * Math.PI / 180 + window.GroundTrackView.siderealRadians(ephemeris.samples[0].timestamp_ms + simulationTimeS * 1000);
            const lat = latDeg * Math.PI / 180;
            return [
              EARTH_EQUATORIAL_RADIUS_KM * Math.cos(lat) * Math.cos(lon),
              EARTH_EQUATORIAL_RADIUS_KM * Math.cos(lat) * Math.sin(lon),
              EARTH_POLAR_RADIUS_KM * Math.sin(lat)
            ];
          }
      
          function drawSurfaceLine(points, scale, cx, cy) {
            let drawing = false;
            ctx.beginPath();
            points.forEach((point) => {
              const rotated = rotate(point);
              if (rotated[2] < 0) {
                drawing = false;
                return;
              }
              const p = projectRotated(rotated, scale, cx, cy);
              if (!drawing) {
                ctx.moveTo(p.x, p.y);
                drawing = true;
              } else {
                ctx.lineTo(p.x, p.y);
              }
            });
            ctx.stroke();
          }
      
          function drawEarthGrid(scale, cx, cy) {
            ctx.strokeStyle = "rgba(230,237,247,.20)";
            ctx.lineWidth = 1;
            for (let lat = -60; lat <= 60; lat += 30) {
              const points = [];
              for (let lon = -180; lon <= 180; lon += 3) points.push(earthPoint(lon, lat));
              drawSurfaceLine(points, scale, cx, cy);
            }
            for (let lon = -180; lon < 180; lon += 30) {
              const points = [];
              for (let lat = -87; lat <= 87; lat += 3) points.push(earthPoint(lon, lat));
              drawSurfaceLine(points, scale, cx, cy);
            }
            ctx.strokeStyle = "rgba(54,163,255,.28)";
            ctx.lineWidth = 1.4;
            const equator = [];
            for (let lon = -180; lon <= 180; lon += 3) equator.push(earthPoint(lon, 0));
            drawSurfaceLine(equator, scale, cx, cy);
          }
      
          function drawEarth(scale, cx, cy) {
            const radius = EARTH_EQUATORIAL_RADIUS_KM * scale;
            const left = Math.floor(cx - radius);
            const top = Math.floor(cy - radius);
            const size = Math.max(1, Math.ceil(radius * 2));
            const globeCanvas = document.createElement("canvas");
            globeCanvas.width = size;
            globeCanvas.height = size;
            const globeCtx = globeCanvas.getContext("2d");
            const globe = globeCtx.createImageData(size, size);
            const sun = [1, 0, 0];
            const sunMag = norm(sun);
            const sidereal = window.GroundTrackView.siderealRadians(ephemeris.samples[0].timestamp_ms + simulationTimeS * 1000);
            for (let py = 0; py < size; py += 1) {
              const sy = (py - radius) / radius;
              for (let px = 0; px < size; px += 1) {
                const sx = (px - radius) / radius;
                const r2 = sx * sx + sy * sy;
                const idx = (py * size + px) * 4;
                if (r2 > 1) continue;
                const sz = Math.sqrt(1 - r2);
                const [wx, wy, wz] = inverseRotate([sx, -sy, sz]);
                const lon = Math.atan2(wy, wx) - sidereal;
                const lat = Math.asin(clamp(wz, -1, 1));
                const tex = sampleEarthTexture(lon, lat);
                const sunCos = dot([wx, wy, wz], sun) / sunMag;
                const day = clamp((sunCos + 0.10) / 0.38, 0, 1);
                const terminator = Math.max(0, 1 - Math.abs(sunCos) / 0.075);
                const light = 0.30 + day * 0.92;
                const rim = clamp(0.92 + (1 - r2) * 0.14, 0.92, 1.06);
                const duskR = terminator * 38;
                const duskG = terminator * 20;
                globe.data[idx] = Math.min(255, tex[0] * light * rim + 10 + duskR);
                globe.data[idx + 1] = Math.min(255, tex[1] * light * rim + 10 + duskG);
                globe.data[idx + 2] = Math.min(255, tex[2] * light * rim + 14);
                globe.data[idx + 3] = 255;
              }
            }
            globeCtx.putImageData(globe, 0, 0);
            ctx.drawImage(globeCanvas, left, top, size, size);
            ctx.save();
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.strokeStyle = "rgba(92, 176, 214, .7)";
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.clip();
            drawEarthGrid(scale, cx, cy);
            ctx.restore();
          }
      
          function earthDiskRadius(scale) {
            return EARTH_EQUATORIAL_RADIUS_KM * scale;
          }

          function pointOccludedByEarth(point, scale, cx, cy) {
            return point.z < 0 && Math.hypot(point.x - cx, point.y - cy) < earthDiskRadius(scale) * .99;
          }

          function drawOrbit(node, samples, scale, cx, cy, layer = "front") {
            const tone = activeTone.get(node) || (node === selectedNode ? "blue" : "muted");
            const color = COLORS[tone] || COLORS.muted;
            const frontLayer = layer === "front";
            const trailLength = 7;
            const tailStart = Math.max(0, Math.min(activeIndex, samples.length - 1) - trailLength);
            const tailEnd = Math.max(0, Math.min(activeIndex, samples.length - 1));
            ctx.beginPath();
            let drawing = false;
            samples.slice(tailStart, tailEnd + 1).forEach((sample, offset) => {
              const idx = tailStart + offset;
              const p = project(kmVec(sample).r, scale, cx, cy);
              const visibleOnLayer = frontLayer ? p.z >= 0 : p.z < 0;
              if (!visibleOnLayer) {
                drawing = false;
                return;
              }
              if (!drawing || idx === 0) {
                ctx.moveTo(p.x, p.y);
                drawing = true;
              } else {
                ctx.lineTo(p.x, p.y);
              }
            });
            ctx.strokeStyle = color;
            ctx.globalAlpha = frontLayer ? (node === selectedNode ? .95 : .42) : (node === selectedNode ? .30 : .16);
            ctx.lineWidth = frontLayer ? (node === selectedNode ? 2.2 : 1.4) : 1;
            ctx.setLineDash(frontLayer ? [] : [5, 7]);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
            const sample = sampleFor(node);
            if (!sample) return;
            const p = project(kmVec(sample).r, scale, cx, cy);
            const satelliteOnLayer = frontLayer ? p.z >= 0 : p.z < 0;
            if (!satelliteOnLayer) return;
            if (!frontLayer && pointOccludedByEarth(p, scale, cx, cy)) return;
            ctx.beginPath();
            ctx.arc(p.x, p.y, node === selectedNode ? 6.5 : 4.5, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.shadowColor = color;
            ctx.globalAlpha = frontLayer ? 1 : .38;
            ctx.shadowBlur = frontLayer ? (node === selectedNode ? 18 : 8) : 0;
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.shadowBlur = 0;
            ctx.fillStyle = frontLayer ? COLORS.text : COLORS.muted;
            ctx.font = "700 12px ui-monospace, monospace";
            ctx.fillText(frontLayer ? node : `${node} FAR`, p.x + 10, p.y - 8);
          }
      
          function render() {
            if (cameraView === "status") {
              canvas.style.display = "none";
              statusBoard.style.display = "grid";
              earthOnlyElements.forEach((element) => element.classList.add("hidden"));
              renderStatusBoard();
              return;
            }
            canvas.style.display = "block";
            statusBoard.style.display = "none";
            earthOnlyElements.forEach((element) => element.classList.remove("hidden"));
            resizeCanvas();
            const rect = canvas.getBoundingClientRect();
            const w = rect.width, h = rect.height;
            if (cameraView === "map") {
              groundTrack.render({ ctx, width: w, height: h, ephemeris,
                relayEphemeris: executionReplay?.bundle.communication?.ephemeris,
                simS: simulationTimeS, tones: activeTone, grid: gridEnabled, selected: selectedNode });
              window.dispatchEvent(new CustomEvent("oslurm:orbit-render", {
                detail: { cameraView: "map", simulationTimeS, activeIndex }
              }));
              return;
            }
            const cx = w * .5 + viewPan.x, cy = h * .52 + viewPan.y;
            const relaySamples = executionReplay?.bundle.communication?.ephemeris?.samples || [];
            const maxRadiusKm = Math.max(9400, ...relaySamples.map((sample) => Math.hypot(...sample.position_eci_m) / 1000));
            const scale = Math.min(w, h) * .34 * viewZoom / maxRadiusKm;
            ctx.clearRect(0, 0, w, h);
            ctx.fillStyle = "#060911";
            ctx.fillRect(0, 0, w, h);
            if (gridEnabled) {
              ctx.strokeStyle = "rgba(37,54,76,.48)";
              ctx.lineWidth = 1;
              for (let x = 0; x < w; x += 48) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
              for (let y = 0; y < h; y += 48) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
            }
            nodes.forEach((node) => drawOrbit(node, byNode.get(node) || [], scale, cx, cy, "back"));
            drawEarth(scale, cx, cy);
            nodes.forEach((node) => drawOrbit(node, byNode.get(node) || [], scale, cx, cy, "front"));
            window.dispatchEvent(new CustomEvent("oslurm:orbit-render", {
              detail: {
                frame: renderFrame++,
                ctx,
                scale,
                earth: {
                  fidelity: "ellipsoid:wgs84",
                  equatorialRadiusKm: EARTH_EQUATORIAL_RADIUS_KM,
                  polarRadiusKm: EARTH_POLAR_RADIUS_KM
                },
                cx,
                cy,
                width: w,
                height: h,
                cameraView,
                activeIndex,
                simulationTimeS,
                sampleCount: Math.max(1, ...nodes.map((node) => (byNode.get(node) || []).length)),
                nodes: [...nodes],
                sampleFor,
                kmVec,
                project,
                colors: COLORS
              }
            }));
          }
      
          function beginDrag(event) {
            if (cameraView === "status") return;
            const mode = event.ctrlKey ? "pan" : pointerMode;
            if (mode === "select") {
              pickSatellite(event.clientX, event.clientY);
              return;
            }
            dragState = {
              mode,
              x: event.clientX,
              y: event.clientY,
              panX: viewPan.x,
              panY: viewPan.y,
              yaw: viewAngles.yaw,
              pitch: viewAngles.pitch
            };
            canvas.classList.add("dragging");
            canvas.setPointerCapture(event.pointerId);
          }
      
          function dragOrbit(event) {
            if (!dragState) return;
            const dx = event.clientX - dragState.x;
            const dy = event.clientY - dragState.y;
            if (cameraView === "map") {
              groundTrack.panBy(dx, dy);
              dragState.x = event.clientX; dragState.y = event.clientY;
              render(); return;
            }
            if (dragState.mode === "pan") {
              viewPan = { x: dragState.panX + dx, y: dragState.panY + dy };
            } else {
              viewAngles = {
                yaw: dragState.yaw + dx * 0.008,
                pitch: clamp(dragState.pitch + dy * 0.006, -1.52, 1.52)
              };
            }
            render();
          }
      
          function endDrag(event) {
            if (!dragState) return;
            dragState = null;
            canvas.classList.remove("dragging");
            if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
          }
      
          function zoomOrbit(event) {
            if (cameraView === "status") return;
            event.preventDefault();
            const factor = event.deltaY < 0 ? 1.08 : 0.92;
            if (cameraView === "map") { groundTrack.zoomBy(factor); render(); return; }
            viewZoom = clamp(viewZoom * factor, 0.40, 2.8);
            render();
          }
      
          async function loadEphemeris() {
            try {
              executionReplay = await window.ExecutionTraceReplay.load();
            } catch (error) {
              commandState.textContent = "trace unavailable";
              commandOutput.textContent = error.message;
            }
            try {
              if (executionReplay) {
                ephemeris = executionReplay.bundle.ephemeris;
                dataSource.textContent = `${executionReplay.result.gmat_backend} GMAT / ${executionReplay.result.execution_backend} / ${executionReplay.horizonS}s`;
              } else {
                const response = await fetch("gmat-events.json", { cache: "no-store" });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                ephemeris = await response.json();
                dataSource.textContent = `GMAT ECI samples loaded: ${ephemeris.samples.length}`;
              }
            } catch (error) {
              ephemeris = fallbackEphemeris;
              dataSource.textContent = `fallback ECI samples: ${error.message}`;
            }
            groupSamples(ephemeris);
            commandInput.readOnly = true;
            sendCommand.disabled = !executionReplay;
            sendCommand.title = "Replay recorded execution";
            if (executionReplay) commandState.textContent = "recorded";
            if (executionReplay) {
              const result = executionReplay.result;
              root.querySelector("#backend").textContent = `GMAT ${result.gmat_backend} / ${result.execution_backend === "slurm" ? "SLURM REAL" : "LOCAL"}`;
              root.querySelector("#schedulerPolicy").textContent = result.policy;
              root.querySelector("#schedulerConstraint").textContent = `${result.eclipse_throughput_factor}x`;
              root.querySelector("#schedulerConstraintLabel").textContent = result.autonomy ? "authority" : "eclipse throughput";
              root.querySelector("#groundStatus").textContent = result.autonomy ? "connected" : "n/a";
              root.querySelector("#schedulerRate").textContent = `${result.iterations_per_sim_s} iter/sim s`;
            }
            setupControls();
            makeNodeCards();
            updateInspector();
            setClock(0);
            eventStore = [];
            renderEvents();
            window.dispatchEvent(new CustomEvent("oslurm:ephemeris-loaded", {
              detail: {
                ephemeris,
                execution: executionReplay?.result || null,
                communication: executionReplay?.bundle.communication || null,
                earth: {
                  fidelity: "ellipsoid:wgs84",
                  equatorialRadiusKm: EARTH_EQUATORIAL_RADIUS_KM,
                  polarRadiusKm: EARTH_POLAR_RADIUS_KM
                },
                nodes: [...nodes],
                sampleFor,
                kmVec
              }
            }));
            render();
          }
      
          sendCommand.addEventListener("click", runCommandSimulation);
          commandInput.addEventListener("input", () => updateJobStrip());
          resetCommand.addEventListener("click", () => {
            resetConsole();
          });
          canvas.addEventListener("pointerdown", beginDrag);
          canvas.addEventListener("pointermove", dragOrbit);
          canvas.addEventListener("pointerup", endDrag);
          canvas.addEventListener("pointercancel", endDrag);
          canvas.addEventListener("wheel", zoomOrbit, { passive: false });
          window.addEventListener("resize", render);
          updatePointerHint();
          loadEarthTexture();
          loadEphemeris();
    }
  }

  window.MissionControlApp = MissionControlApp;
  window.addEventListener("DOMContentLoaded", () => new MissionControlApp().start());
})();

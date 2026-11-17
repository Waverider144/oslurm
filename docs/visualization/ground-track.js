(() => {
  "use strict";
  const TAU = Math.PI * 2;
  const wrap = value => ((value + 180) % 360 + 360) % 360 - 180;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

  function siderealRadians(timestampMs) {
    const days = timestampMs / 86400000 + 2440587.5 - 2451545;
    const centuries = days / 36525;
    return ((280.46061837 + 360.98564736629 * days + 0.000387933 * centuries ** 2 - centuries ** 3 / 38710000) % 360) * Math.PI / 180;
  }

  function subpoint(sample) {
    const [x, y, z] = sample.position_fixed_m || sample.position_eci_m;
    const p = Math.hypot(x, y), a = 6378137, b = 6356752.314245;
    const e2 = 1 - b * b / (a * a), ep2 = (a * a - b * b) / (b * b);
    const theta = Math.atan2(z * a, p * b);
    const lat = Math.atan2(z + ep2 * b * Math.sin(theta) ** 3, p - e2 * a * Math.cos(theta) ** 3);
    return { lon: wrap((Math.atan2(y, x) - (sample.position_fixed_m ? 0 : siderealRadians(sample.timestamp_ms))) * 180 / Math.PI), lat: lat * 180 / Math.PI };
  }

  class GroundTrackView {
    constructor(onReady) {
      this.zoom = 1;
      this.pan = { x: 0, y: 0 };
      this.points = new Map();
      this.texture = new Image();
      this.texture.onload = onReady;
      this.texture.src = "earth-blue-marble.jpg";
    }

    reset() { this.zoom = 1; this.pan = { x: 0, y: 0 }; }
    zoomBy(factor) { this.zoom = clamp(this.zoom * factor, 1, 6); }
    panBy(x, y) { this.pan.x += x; this.pan.y += y; }
    pick(x, y) {
      const nearby = [...this.points.entries()].map(([node, p]) => ({ node, distance: Math.hypot(p.x - x, p.y - y) }));
      nearby.sort((a, b) => a.distance - b.distance);
      return nearby[0]?.distance < 22 ? nearby[0].node : null;
    }

    render({ ctx, width, height, ephemeris, relayEphemeris, simS, tones, grid, selected }) {
      ctx.fillStyle = "#060911";
      ctx.fillRect(0, 0, width, height);
      const mapWidth = Math.max(1, width - 28);
      const mapHeight = Math.max(1, Math.min(mapWidth / 2, height - 168));
      const bounds = { x: 14, y: Math.max(92, (height - mapHeight) / 2), width: mapWidth, height: mapHeight };
      this.pan.x = clamp(this.pan.x, -mapWidth * (this.zoom - 1) / 2, mapWidth * (this.zoom - 1) / 2);
      this.pan.y = clamp(this.pan.y, -mapHeight * (this.zoom - 1) / 2, mapHeight * (this.zoom - 1) / 2);
      const cx = bounds.x + mapWidth / 2, cy = bounds.y + mapHeight / 2;
      const project = ({ lon, lat }) => ({
        x: cx + lon / 360 * mapWidth * this.zoom + this.pan.x,
        y: cy - lat / 180 * mapHeight * this.zoom + this.pan.y
      });
      const epoch = Math.min(...ephemeris.samples.map(s => s.timestamp_ms));
      const currentMs = epoch + simS * 1000;
      const byNode = new Map();
      for (const sample of [...ephemeris.samples, ...(relayEphemeris?.samples || [])]) {
        if (!byNode.has(sample.node_id)) byNode.set(sample.node_id, []);
        byNode.get(sample.node_id).push(sample);
      }
      ctx.save();
      ctx.beginPath(); ctx.rect(bounds.x, bounds.y, mapWidth, mapHeight); ctx.clip();
      ctx.save();
      ctx.translate(cx + this.pan.x, cy + this.pan.y); ctx.scale(this.zoom, this.zoom); ctx.translate(-cx, -cy);
      if (this.texture.complete && this.texture.naturalWidth) ctx.drawImage(this.texture, bounds.x, bounds.y, mapWidth, mapHeight);
      else { ctx.fillStyle = "#173b50"; ctx.fillRect(bounds.x, bounds.y, mapWidth, mapHeight); }
      const sunLon = -siderealRadians(currentMs);
      const frame = ephemeris.frames?.filter(f => f.timestamp_ms <= currentMs).at(-1);
      for (let lon = -180; lon < 180; lon += 4) {
        if (frame?.sun_fixed_m) {
          const sun = frame.sun_fixed_m, length = Math.hypot(...sun);
          for (let lat = -90; lat < 90; lat += 4) {
            const a = (lon+2)*Math.PI/180, b = (lat+2)*Math.PI/180;
            const cosine = (Math.cos(b)*Math.cos(a)*sun[0] + Math.cos(b)*Math.sin(a)*sun[1] + Math.sin(b)*sun[2]) / length;
            const alpha = clamp((0.08-cosine)/0.2,0,1)*.64;
            if (alpha) { ctx.fillStyle=`rgba(0,0,8,${alpha})`; ctx.fillRect(bounds.x+(lon+180)/360*mapWidth,
              bounds.y+(90-lat-4)/180*mapHeight,mapWidth/90+.5,mapHeight/45+.5); }
          }
          continue;
        }
        const cosine = Math.cos((lon + 2) * Math.PI / 180 - sunLon);
        const alpha = clamp((0.08 - cosine) / 0.2, 0, 1) * 0.64;
        if (alpha) {
          ctx.fillStyle = `rgba(0,0,8,${alpha})`;
          ctx.fillRect(bounds.x + (lon + 180) / 360 * mapWidth, bounds.y, mapWidth / 90 + 0.5, mapHeight);
        }
      }
      ctx.restore();
      if (grid) {
        ctx.strokeStyle = "rgba(224,234,244,.25)"; ctx.lineWidth = 0.7;
        for (let lon = -180; lon <= 180; lon += 30) {
          const p = project({ lon, lat: 0 });
          ctx.beginPath(); ctx.moveTo(p.x, bounds.y); ctx.lineTo(p.x, bounds.y + mapHeight); ctx.stroke();
        }
        for (let lat = -90; lat <= 90; lat += 30) {
          const p = project({ lon: 0, lat });
          ctx.beginPath(); ctx.moveTo(bounds.x, p.y); ctx.lineTo(bounds.x + mapWidth, p.y); ctx.stroke();
        }
      }
      const colors = { blue: "#36a3ff", amber: "#f5b84b", red: "#ff4d5c", green: "#61d394" };
      this.points.clear();
      for (const [node, samples] of byNode) {
        samples.sort((a, b) => a.timestamp_ms - b.timestamp_ms);
        const relay = node.startsWith("RELAY-");
        const color = relay ? colors.green : colors[tones.get(node) || "green"];
        const path = samples.map(sample => ({ ...project(subpoint(sample)), ...subpoint(sample), time: sample.timestamp_ms }));
        for (const future of [true, false]) {
          ctx.strokeStyle = color; ctx.globalAlpha = future ? 0.28 : 0.86;
          ctx.lineWidth = future ? 1 : 1.5; ctx.setLineDash(future ? [3, 5] : []);
          ctx.beginPath(); let previous = null;
          for (const point of path) {
            if ((future && point.time < currentMs - 60000) || (!future && point.time > currentMs)) { previous = null; continue; }
            if (!previous || Math.abs(point.lon - previous.lon) > 180) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
            previous = point;
          }
          ctx.stroke();
        }
        ctx.globalAlpha = 1; ctx.setLineDash([]);
        const sample = samples.filter(s => s.timestamp_ms <= currentMs).at(-1) || samples[0];
        const point = project(subpoint(sample));
        if (point.x < bounds.x || point.x > bounds.x + mapWidth || point.y < bounds.y || point.y > bounds.y + mapHeight) continue;
        if (!relay) this.points.set(node, point);
        ctx.fillStyle = color; ctx.beginPath();
        if (relay) { ctx.moveTo(point.x, point.y - 5); ctx.lineTo(point.x + 5, point.y + 4); ctx.lineTo(point.x - 5, point.y + 4); ctx.closePath(); }
        else ctx.arc(point.x, point.y, 4, 0, TAU);
        ctx.fill();
        if (node === selected) { ctx.strokeStyle = "#fff"; ctx.beginPath(); ctx.arc(point.x, point.y, 7, 0, TAU); ctx.stroke(); }
        ctx.font = "700 10px ui-monospace, monospace";
        ctx.textAlign = point.x > cx ? "right" : "left";
        ctx.fillText(node, point.x + (point.x > cx ? -8 : 8), point.y + (relay ? 16 : -10));
      }
      ctx.restore();
      ctx.strokeStyle = "#526477"; ctx.lineWidth = 1; ctx.strokeRect(bounds.x, bounds.y, mapWidth, mapHeight);
      ctx.font = "10px ui-monospace, monospace"; ctx.fillStyle = "#9bafc2"; ctx.textAlign = "center";
      for (const lon of [-120, -60, 0, 60, 120]) {
        const p = project({ lon, lat: 0 });
        if (p.x > bounds.x && p.x < bounds.x + mapWidth) ctx.fillText(lon === 0 ? "0" : `${Math.abs(lon)}${lon < 0 ? "W" : "E"}`, p.x, bounds.y + mapHeight + 16);
      }
      ctx.textAlign = "left"; ctx.fillText("90N", bounds.x, bounds.y - 8);
      ctx.textAlign = "right"; ctx.fillText("90S", bounds.x + mapWidth, bounds.y + mapHeight + 16);
    }
  }

  GroundTrackView.siderealRadians = siderealRadians;
  GroundTrackView.subpoint = subpoint;
  if (typeof module !== "undefined") module.exports = { subpoint, siderealRadians };
  else window.GroundTrackView = GroundTrackView;
})();

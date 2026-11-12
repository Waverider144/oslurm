const assert = require("node:assert/strict");
const { subpoint, siderealRadians } = require("../docs/visualization/ground-track.js");

const epoch = Date.UTC(2026, 7, 22);
const angle = siderealRadians(epoch);
function inertial(longitude, latitude, timestamp = epoch) {
  const lon = longitude * Math.PI / 180 + siderealRadians(timestamp);
  const lat = latitude * Math.PI / 180;
  const a = 6378137, e2 = 0.00669437999014;
  const n = a / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
  return { timestamp_ms: timestamp, position_eci_m: [
    (n + 550000) * Math.cos(lat) * Math.cos(lon),
    (n + 550000) * Math.cos(lat) * Math.sin(lon),
    (n * (1 - e2) + 550000) * Math.sin(lat)
  ] };
}
for (const [lon, lat] of [[0, 0], [179.9, 45], [-179.9, -60], [100, 89.99]]) {
  const point = subpoint(inertial(lon, lat));
  assert.ok(Math.abs(point.lon - lon) < 1e-6);
  assert.ok(Math.abs(point.lat - lat) < 1e-6);
}
const fixed = inertial(0, 0);
const later = subpoint({ ...fixed, timestamp_ms: epoch + 3600000 });
assert.ok(Math.abs(later.lon + 15.04106864) < 1e-5);
assert.ok(Number.isFinite(angle));
console.log("Ground track: WGS84 subpoints, dateline and sidereal rotation passed");

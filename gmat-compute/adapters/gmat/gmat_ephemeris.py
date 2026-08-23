#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

EARTH_RADIUS_KM = 6371.0
GMAT_EPOCH_UNIX_MS = 1787356800000


def circular_state(radius_km: float, phase_deg: float, inclination_deg: float = 2.0):
    mu = 398600.4418
    phase = math.radians(phase_deg)
    inc = math.radians(inclination_deg)
    speed = math.sqrt(mu / radius_km)
    x = radius_km * math.cos(phase)
    y0 = radius_km * math.sin(phase)
    z = y0 * math.sin(inc)
    y = y0 * math.cos(inc)
    vx = -speed * math.sin(phase)
    vy0 = speed * math.cos(phase)
    vz = vy0 * math.sin(inc)
    vy = vy0 * math.cos(inc)
    return x, y, z, vx, vy, vz


def gmat_script(report_path: Path) -> str:
    phases = {"sat001": 100.0, "sat002": 100.0, "sat003": 10.0, "sat004": 280.0}
    lines: list[str] = []
    for node, phase in phases.items():
        x, y, z, vx, vy, vz = circular_state(6921.0, phase)
        lines += [
            f"Create Spacecraft {node};",
            f"{node}.DateFormat = UTCGregorian;",
            f"{node}.Epoch = '22 Aug 2026 00:00:00.000';",
            f"{node}.CoordinateSystem = EarthMJ2000Eq;",
            f"{node}.DisplayStateType = Cartesian;",
            f"{node}.X = {x:.12f};",
            f"{node}.Y = {y:.12f};",
            f"{node}.Z = {z:.12f};",
            f"{node}.VX = {vx:.12f};",
            f"{node}.VY = {vy:.12f};",
            f"{node}.VZ = {vz:.12f};",
            "",
        ]
    lines += [
        "Create ForceModel FM;",
        "FM.CentralBody = Earth;",
        "FM.PrimaryBodies = {Earth};",
        "FM.GravityField.Earth.Degree = 0;",
        "FM.GravityField.Earth.Order = 0;",
        "FM.SRP = Off;",
        "FM.RelativisticCorrection = Off;",
        "FM.ErrorControl = RSSStep;",
        "",
        "Create Propagator Prop;",
        "Prop.FM = FM;",
        "",
        "Create ReportFile RF;",
        f"RF.Filename = '{report_path}';",
        "RF.Precision = 16;",
        "RF.WriteHeaders = true;",
        "RF.FixedWidth = false;",
        "RF.Delimiter = ',';",
        "RF.WriteReport = true;",
        "",
        "Create Variable i;",
        "",
        "BeginMissionSequence;",
    ]
    cols = []
    for node in phases:
        cols += [f"{node}.A1ModJulian", f"{node}.X", f"{node}.Y", f"{node}.Z", f"{node}.VX", f"{node}.VY", f"{node}.VZ"]
    lines.append("Report RF " + " ".join(cols) + ";")
    lines.append("For i = 1:12")
    lines.append("  Propagate Prop(sat001, sat002, sat003, sat004) {sat001.ElapsedSecs = 60};")
    lines.append("  Report RF " + " ".join(cols) + ";")
    lines.append("EndFor")
    return "\n".join(lines) + "\n"


def in_sunlight(position_km):
    x, y, z = position_km
    return not (x < 0.0 and math.sqrt(y * y + z * z) < EARTH_RADIUS_KM)


def parse_report(report_path: Path):
    rows = [line.strip() for line in report_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data_rows = [row for row in rows if not row.startswith("sat")]
    nodes = ["sat001", "sat002", "sat003", "sat004"]
    samples = []
    events = []
    last_sun = {}
    for row_idx, row in enumerate(data_rows):
        values = [float(x.strip()) for x in row.split(",")]
        timestamp_ms = GMAT_EPOCH_UNIX_MS + row_idx * 60_000
        for node_idx, node in enumerate(nodes):
            base = node_idx * 7
            x, y, z = values[base + 1], values[base + 2], values[base + 3]
            vx, vy, vz = values[base + 4], values[base + 5], values[base + 6]
            sun = in_sunlight((x, y, z))
            if node in last_sun and last_sun[node] != sun:
                events.append({"type": "ECLIPSE_EXIT" if sun else "ECLIPSE_ENTRY", "node_id": node, "timestamp_ms": timestamp_ms})
            last_sun[node] = sun
            samples.append({
                "node_id": node,
                "timestamp_ms": timestamp_ms,
                "position_eci_m": [x * 1000, y * 1000, z * 1000],
                "velocity_eci_mps": [vx * 1000, vy * 1000, vz * 1000],
                "in_sunlight": sun,
            })
    return {"samples": samples, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gmat", default="../third_party/GMAT-R2026a-fixed/bin/GmatConsole")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    exe = Path(args.gmat).resolve()
    if not exe.exists():
        print(f"GMAT backend: unavailable ({exe})")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        report = tmp_path / "gmat_compute_report.csv"
        script = tmp_path / "gmat_compute.script"
        script.write_text(gmat_script(report), encoding="utf-8")
        result = subprocess.run(
            [str(exe), "--run", str(script), "--exit", "--verbose", "off"],
            cwd=exe.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print((result.stdout + result.stderr)[-4000:])
            return result.returncode
        data = parse_report(report)
    Path(args.output).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("GMAT backend: REAL")
    print("GMAT version: R2026a")
    print(f"samples: {len(data['samples'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

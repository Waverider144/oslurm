#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from providers.gmat.backend import detect_backend


EARTH_RADIUS_KM = 6371.0
GMAT_EPOCH_UNIX_MS = 1787356800000


def _circular_state(radius_km: float, phase_deg: float, inclination_deg: float = 2.0) -> tuple[float, float, float, float, float, float]:
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


def write_gmat_script(report_path: Path, horizon_s: int = 720, step_s: int = 60, include_relays: bool = False) -> str:
    if horizon_s <= 0 or step_s <= 0 or horizon_s % step_s:
        raise ValueError("horizon_s must be a positive multiple of step_s")
    phases = {"sat001": 100.0, "sat002": 190.0, "sat003": 280.0, "sat004": 10.0}
    if include_relays:
        phases.update(relay_a=0.0, relay_b=120.0)
    lines = []
    for node, phase in phases.items():
        x, y, z, vx, vy, vz = _circular_state(42164.0 if node.startswith("relay") else 6921.0, phase)
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
    report_cols = []
    for node in phases:
        report_cols += [f"{node}.A1ModJulian", f"{node}.X", f"{node}.Y", f"{node}.Z", f"{node}.VX", f"{node}.VY", f"{node}.VZ"]
    lines.append("Report RF " + " ".join(report_cols) + ";")
    lines.append(f"For i = 1:{horizon_s // step_s}")
    lines.append(f"  Propagate Prop({', '.join(phases)}) {{sat001.ElapsedSecs = {step_s}}};")
    lines.append("  Report RF " + " ".join(report_cols) + ";")
    lines.append("EndFor")
    return "\n".join(lines) + "\n"


def _in_sunlight(position_km: tuple[float, float, float]) -> bool:
    x, y, z = position_km
    return not (x < 0.0 and math.sqrt(y * y + z * z) < EARTH_RADIUS_KM)


def parse_gmat_report(report_path: Path, include_relays: bool = False) -> dict:
    samples = []
    events = []
    last_sun: dict[str, bool] = {}
    rows = [line.strip() for line in report_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data_rows = [row for row in rows if not row.startswith("sat")]
    nodes = ["sat001", "sat002", "sat003", "sat004"]
    if include_relays:
        nodes += ["RELAY-A", "RELAY-B"]
    epoch_a1 = None
    for row in data_rows:
        values = [float(x.strip()) for x in row.split(",")]
        if epoch_a1 is None:
            epoch_a1 = values[0]
        timestamp_ms = GMAT_EPOCH_UNIX_MS + round((values[0] - epoch_a1) * 86_400_000)
        for node_idx, node in enumerate(nodes):
            base = node_idx * 7
            x, y, z = values[base + 1], values[base + 2], values[base + 3]
            vx, vy, vz = values[base + 4], values[base + 5], values[base + 6]
            sunlight = _in_sunlight((x, y, z))
            if node in last_sun and last_sun[node] != sunlight:
                events.append(
                    {
                        "type": "ECLIPSE_EXIT" if sunlight else "ECLIPSE_ENTRY",
                        "node_id": node,
                        "timestamp_ms": timestamp_ms,
                    }
                )
            last_sun[node] = sunlight
            samples.append(
                {
                    "node_id": node,
                    "timestamp_ms": timestamp_ms,
                    "position_eci_m": [x * 1000.0, y * 1000.0, z * 1000.0],
                    "velocity_eci_mps": [vx * 1000.0, vy * 1000.0, vz * 1000.0],
                    "in_sunlight": sunlight,
                }
            )
    return {"samples": samples, "events": events}


def real_gmat_ephemeris(executable: str, horizon_s: int = 720, step_s: int = 60, include_relays: bool = False) -> dict:
    exe = Path(executable)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        report_path = tmp_path / "oslurm_gmat_report.csv"
        script_path = tmp_path / "oslurm_leo_demo.script"
        script_path.write_text(write_gmat_script(report_path, horizon_s, step_s, include_relays), encoding="utf-8")
        result = subprocess.run(
            [str(exe), "--run", str(script_path), "--exit", "--verbose", "off"],
            cwd=str(exe.parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stdout + result.stderr)[-4000:])
        return parse_gmat_report(report_path, include_relays)


def mock_leo_ephemeris(horizon_s: int = 720, step_s: int = 60) -> dict:
    t0 = 1787220000000
    nodes = ["sat001", "sat002", "sat003", "sat004"]
    samples = []
    events = []
    radius = 6_371_000.0 + 550_000.0
    period_s = 5400.0
    for idx, node in enumerate(nodes):
        phase = idx * math.pi / 2.0
        was_sun = None
        for t_s in range(0, horizon_s + 1, step_s):
            theta = 2.0 * math.pi * t_s / period_s + phase
            pos = (radius * math.cos(theta), radius * math.sin(theta), 120_000.0 * math.sin(theta * 0.5))
            vel = (-radius * math.sin(theta) * 2.0 * math.pi / period_s, radius * math.cos(theta) * 2.0 * math.pi / period_s, 0.0)
            in_sun = math.cos(theta) >= -0.15
            if node in {"sat001", "sat002"} and t_s >= 240:
                in_sun = False
            if was_sun is not None and was_sun != in_sun:
                events.append(
                    {
                        "type": "ECLIPSE_EXIT" if in_sun else "ECLIPSE_ENTRY",
                        "node_id": node,
                        "timestamp_ms": t0 + t_s * 1000,
                    }
                )
            was_sun = in_sun
            samples.append(
                {
                    "node_id": node,
                    "timestamp_ms": t0 + t_s * 1000,
                    "position_eci_m": list(pos),
                    "velocity_eci_mps": list(vel),
                    "in_sunlight": in_sun,
                }
            )
    return {"samples": samples, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--horizon-s", type=int, default=720)
    parser.add_argument("--step-s", type=int, default=60)
    args = parser.parse_args()
    if args.horizon_s <= 0 or args.step_s <= 0 or args.horizon_s % args.step_s:
        parser.error("--horizon-s must be a positive multiple of --step-s")

    backend = detect_backend()
    if backend.real:
        print(f"GMAT backend: {backend.mode}")
        if backend.executable:
            print(f"Executable: {backend.executable}")
            Path(args.output).write_text(json.dumps(real_gmat_ephemeris(backend.executable, args.horizon_s, args.step_s), indent=2), encoding="utf-8")
            return 0
        raise SystemExit("Real GMAT Python API was detected but is not implemented in this adapter")
    if not args.allow_mock:
        print("GMAT backend: unavailable")
        print(f"Reason: {backend.reason}")
        return 2
    print("GMAT backend: mock")
    print(f"Reason: {backend.reason}")
    Path(args.output).write_text(json.dumps(mock_leo_ephemeris(args.horizon_s, args.step_s), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""GMAT-native fixed/inertial states with an explicit higher-fidelity force model."""
from __future__ import annotations

import math
import datetime
import hashlib
import subprocess
import tempfile
from pathlib import Path

from .adapter import parse_gmat_report, write_gmat_script


def runtime_inputs(executable: str, start_ms: int, end_ms: int):
    root = Path(executable).resolve().parent.parent
    files = [root / "bin/gmat_startup_file.txt", root / "data/gravity/earth/JGM2.cof",
             root / "data/planetary_coeff/eopc04_08.62-now", root / "data/planetary_coeff/NUTATION.DAT",
             root / "data/time/tai-utc.dat"]
    hashes = {}
    for path in files:
        with path.open("rb") as stream:
            hashes[str(path.relative_to(root))] = hashlib.file_digest(stream, "sha256").hexdigest()
    dates = []
    for line in files[2].read_text().splitlines():
        fields = line.split()
        if len(fields) >= 4 and len(fields[0]) == 4 and fields[0].isdigit():
            dates.append(datetime.date(*map(int, fields[:3])))
    start = datetime.datetime.fromtimestamp(start_ms / 1000, datetime.timezone.utc).date()
    end = datetime.datetime.fromtimestamp(end_ms / 1000, datetime.timezone.utc).date()
    if not dates or start < min(dates) or end > max(dates):
        raise ValueError("mission epoch outside packaged EOP coverage; update GMAT data before running")
    return {"packaged_input_sha256": hashes, "eop_first_date": str(min(dates)), "eop_last_date": str(max(dates))}


def fixed_site(site):
    lat, lon = math.radians(float(site["latitude_deg"])), math.radians(float(site["longitude_deg"]))
    alt = float(site.get("altitude_m", 0))
    mask = float(site.get("min_elevation_deg", 10))
    if not (-math.pi / 2 <= lat <= math.pi / 2 and -math.pi <= lon <= math.pi and math.isfinite(alt) and alt >= 0
            and math.isfinite(mask) and 0 <= mask < 90):
        raise ValueError("invalid ground site")
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)
    n = 6378137 / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    return ((n + alt) * up[0], (n + alt) * up[1], (n * (1 - e2) + alt) * up[2]), up


def rotation_from_states(inertial, fixed):
    def unit(v):
        length = math.sqrt(sum(x*x for x in v))
        if length < 1e-12:
            raise ValueError("degenerate native frame basis")
        return [x/length for x in v]
    def cross(a,b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    def basis(vectors):
        x = unit(vectors[0])
        z = unit(cross(x, vectors[1]))
        return [x, cross(z,x), z]
    a,b = basis(inertial), basis(fixed)
    return [[sum(a[k][i]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mission_script(report: Path, sites: dict, horizon_s: int, step_s: int) -> str:
    script = write_gmat_script(report, horizon_s, step_s, include_relays=True)
    script = script.replace("FM.GravityField.Earth.Degree = 0;", "FM.GravityField.Earth.Degree = 8;\nFM.GravityField.Earth.PotentialFile = 'JGM2.cof';\nFM.PointMasses = {Sun, Luna};")
    script = script.replace("FM.GravityField.Earth.Order = 0;", "FM.GravityField.Earth.Order = 8;")
    script = script.replace("Prop.FM = FM;", "Prop.FM = FM;\nProp.Accuracy = 1e-12;\nProp.MaxStep = 10;")
    script = script.replace("BeginMissionSequence;", "Create CoordinateSystem SunMJ2000Eq;\nSunMJ2000Eq.Origin = Sun;\nSunMJ2000Eq.Axes = MJ2000Eq;\nBeginMissionSequence;")
    declarations, assignments, columns = [], [], []
    for index, site in enumerate(sites.values()):
        xyz, _ = fixed_site(site)
        name = f"GroundProxy{index}"
        declarations.extend([f"Create Spacecraft {name};", f"{name}.CoordinateSystem = EarthFixed;",
            f"{name}.DateFormat = UTCGregorian;", f"{name}.Epoch = '22 Aug 2026 00:00:00.000';",
            f"{name}.DisplayStateType = Cartesian;"])
        assignments.append(f"{name}.A1ModJulian = sat001.A1ModJulian;")
        for axis, value in zip(("X", "Y", "Z"), xyz):
            declarations.append(f"{name}.{axis} = {value / 1000:.15g};")
            assignments.append(f"{name}.{axis} = {value / 1000:.15g};")
        columns.extend(f"{name}.EarthMJ2000Eq.{axis}" for axis in ("X", "Y", "Z"))
    fixed = [f"{node}.EarthFixed.{axis}" for node in ("sat001", "sat002", "sat003", "sat004", "relay_a", "relay_b")
             for axis in ("X", "Y", "Z")]
    script = script.replace("BeginMissionSequence;", "\n".join(declarations) + "\nBeginMissionSequence;")
    lines = []
    for line in script.splitlines():
        if line.strip().startswith("Report RF "):
            lines.extend(assignments)
            line = line.rstrip(";") + " " + " ".join(fixed + columns + [f"sat001.SunMJ2000Eq.{a}" for a in ("X", "Y", "Z")]) + ";"
        lines.append(line)
    return "\n".join(lines) + "\n"


def real_mission_ephemeris(executable: str, sites: dict, horizon_s: int, step_s: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        report, script = Path(tmp) / "states.csv", Path(tmp) / "mission.script"
        script.write_text(mission_script(report, sites, horizon_s, step_s))
        result = subprocess.run([executable, "--run", str(script), "--exit", "--verbose", "off"],
            cwd=str(Path(executable).parent), capture_output=True, text=True, timeout=120)
        if result.returncode or not report.exists():
            raise RuntimeError((result.stdout + result.stderr)[-5000:])
        data = parse_gmat_report(report, include_relays=True)
        rows = [list(map(float, row.split(","))) for row in report.read_text().splitlines()
                if row.strip() and not row.startswith("sat")]
        for index, row in enumerate(rows):
            if len(row) != 63 + 3 * len(sites):
                raise ValueError("unexpected GMAT native-frame report layout")
            timestamp = data["samples"][index * 6]["timestamp_ms"]
            sun = [row[axis + 1] * 1000 - row[-3 + axis] * 1000 for axis in range(3)]
            sun_norm = math.sqrt(sum(v*v for v in sun))
            for node in range(6):
                sample = data["samples"][index * 6 + node]
                sample["position_fixed_m"] = [v * 1000 for v in row[42 + node * 3:45 + node * 3]]
                sample["sun_eci_m"] = sun
                projection = sum(a * b for a,b in zip(sample["position_eci_m"], sun)) / sun_norm
                perpendicular2 = sum(v*v for v in sample["position_eci_m"]) - projection**2
                sample["in_sunlight"] = not (projection < 0 and perpendicular2 < 6378137**2)
            for ground_index, (name, site) in enumerate(sites.items()):
                data.setdefault("ground_samples", []).append({"node_id": name, "timestamp_ms": timestamp,
                    "position_eci_m": [v * 1000 for v in row[60 + ground_index * 3:63 + ground_index * 3]],
                    "position_fixed_m": list(fixed_site(site)[0])})
            samples = data["samples"][index*6:index*6+6]
            rotation = rotation_from_states([s["position_eci_m"] for s in samples[:2]],
                                             [s["position_fixed_m"] for s in samples[:2]])
            data.setdefault("frames", []).append({"timestamp_ms": timestamp, "fixed_to_eci": rotation,
                "sun_eci_m": sun, "sun_fixed_m": [sum(rotation[j][i]*sun[j] for j in range(3)) for i in range(3)]})
        data["frame_model"] = "GMAT EarthFixed/EarthMJ2000Eq native conversion"
        data["force_model"] = "JGM2 8x8 + Sun/Luna point masses; accuracy 1e-12; max step 10s; drag/SRP off"
        data["shadow_model"] = "cylindrical Earth shadow using GMAT Sun direction; penumbra unmodeled"
        data["events"] = []
        previous = {}
        for sample in data["samples"]:
            name, light = sample["node_id"], sample["in_sunlight"]
            if name in previous and previous[name] != light:
                data["events"].append({"node_id": name, "timestamp_ms": sample["timestamp_ms"],
                    "type": "ECLIPSE_EXIT" if light else "ECLIPSE_ENTRY"})
            previous[name] = light
        data["gmat_script"] = script.read_text()
        data["runtime_inputs"] = runtime_inputs(executable, data["samples"][0]["timestamp_ms"], data["samples"][-1]["timestamp_ms"])
        return data

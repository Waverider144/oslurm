"""WGS84 ground sites with approximate GMST rotation into the orbital ECI frame."""
from __future__ import annotations

import math


def ground_state(site: dict, timestamp_ms: float) -> tuple[tuple, tuple]:
    lat = float(site["latitude_deg"])
    lon = float(site["longitude_deg"])
    altitude = float(site.get("altitude_m", 0))
    elevation = float(site.get("min_elevation_deg", 10))
    if (not all(math.isfinite(v) for v in (lat, lon, altitude, elevation, timestamp_ms))
            or not -90 <= lat <= 90 or not -180 <= lon <= 180 or altitude < 0 or not 0 <= elevation < 90):
        raise ValueError("invalid ground site or epoch")
    latitude = math.radians(lat)
    days = timestamp_ms / 86400000 + 2440587.5 - 2451545.0
    centuries = days / 36525
    angle = math.radians((280.46061837 + 360.98564736629 * days
                         + 0.000387933 * centuries ** 2 - centuries ** 3 / 38710000 + lon) % 360)
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)
    n = 6378137 / math.sqrt(1 - e2 * math.sin(latitude) ** 2)
    normal = (math.cos(latitude) * math.cos(angle), math.cos(latitude) * math.sin(angle), math.sin(latitude))
    position = ((n + altitude) * normal[0], (n + altitude) * normal[1],
                (n * (1 - e2) + altitude) * normal[2])
    return position, normal


def above_mask(site: dict, timestamp_ms: float, target: tuple) -> bool:
    position, normal = ground_state(site, timestamp_ms)
    delta = tuple(b - a for a, b in zip(position, target))
    distance = math.sqrt(sum(v * v for v in delta))
    return distance > 0 and sum(a * b for a, b in zip(delta, normal)) / distance >= math.sin(
        math.radians(float(site.get("min_elevation_deg", 10))))


def with_ground_sites(ephemeris: dict, sites: dict) -> dict:
    samples = [dict(sample) for sample in ephemeris["samples"]]
    ids = {s["node_id"] for s in samples}
    if ids.intersection(sites):
        raise ValueError("ground site duplicates orbital node ID")
    for timestamp in sorted({s["timestamp_ms"] for s in samples}):
        for node, site in sites.items():
            position, _ = ground_state(site, timestamp)
            samples.append({"node_id": node, "timestamp_ms": timestamp, "position_eci_m": list(position)})
    return {**ephemeris, "samples": samples, "ground_stations": sites}

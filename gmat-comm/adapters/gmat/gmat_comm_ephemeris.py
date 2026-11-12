from __future__ import annotations

import argparse
import json
import math
from itertools import combinations
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oslurm.visibility import AnalyticEllipsoidVisibilityProvider, VisibilityQuery
from oslurm.network.ground import above_mask, ground_state


def norm(vec):
    return math.sqrt(sum(x * x for x in vec))


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def convert(input_path: Path, output_path: Path, max_range_m: float) -> dict:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    by_time = {}
    for sample in data["samples"]:
        by_time.setdefault(sample["timestamp_ms"], []).append(sample)
    provider = AnalyticEllipsoidVisibilityProvider()
    contacts_by_pair = {}
    metrics = {"potential_pairs": 0, "geometry_tests": 0, "pruned_pairs": 0, "contact_windows_generated": 0}
    for timestamp_ms, samples in sorted(by_time.items()):
        for left, right in combinations(samples, 2):
            metrics["potential_pairs"] += 1
            distance = norm(sub(left["position_eci_m"], right["position_eci_m"]))
            if distance > max_range_m:
                metrics["pruned_pairs"] += 1
                continue
            metrics["geometry_tests"] += 1
            result = provider.evaluate(VisibilityQuery(
                source_id=left["node_id"],
                destination_id=right["node_id"],
                source_position_eci_m=tuple(left["position_eci_m"]),
                destination_position_eci_m=tuple(right["position_eci_m"]),
            ))
            if not result.geometrically_visible:
                continue
            pair = tuple(sorted([left["node_id"], right["node_id"]]))
            contacts_by_pair.setdefault(pair, []).append({
                "contact_id": f"{left['node_id']}:{right['node_id']}:{timestamp_ms}",
                "source": left["node_id"],
                "destination": right["node_id"],
                "start_ms": timestamp_ms,
                "end_ms": timestamp_ms + 60_000,
                "kind": "CommunicationToCommunication",
                "range_m": distance,
                "line_of_sight": True,
                "occultation_margin_m": result.limb_clearance_m,
                "visibility": {
                    "geometrically_visible": result.geometrically_visible,
                    "earth_occulted": result.earth_occulted,
                    "reason": result.reason.value,
                    "fidelity": result.fidelity,
                },
            })
    contacts = slice_contacts(contacts_by_pair)
    metrics["contact_windows_generated"] = len(contacts)
    metrics.update(provider.metrics.as_dict())
    output = {"source": "GMAT", "adapter": "gmat_comm_ephemeris", "contacts": contacts, "metrics": metrics}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    return output


def slice_contacts(contacts_by_pair):
    windows = []
    for pair, samples in sorted(contacts_by_pair.items()):
        del pair
        samples = sorted(samples, key=lambda item: item["start_ms"])
        current = None
        previous = None
        for sample in samples:
            if current is None:
                current = dict(sample)
            elif previous and sample["start_ms"] <= previous["end_ms"]:
                current["end_ms"] = sample["end_ms"]
                current["range_m"] = max(current["range_m"], sample["range_m"])
                current["occultation_margin_m"] = min(current["occultation_margin_m"], sample["occultation_margin_m"])
            else:
                windows.append(current)
                current = dict(sample)
            previous = sample
        if current is not None:
            windows.append(current)
    for index, window in enumerate(windows, start=1):
        window["contact_id"] = f"{window['source']}:{window['destination']}:window-{index:04d}"
    return windows


def interval_contacts(data: dict, max_range_m: float) -> dict:
    """Conservative sampled windows; never extend past the final ephemeris epoch."""
    by_time = {}
    for sample in data["samples"]:
        by_time.setdefault(sample["timestamp_ms"], {})[sample["node_id"]] = sample
    times = sorted(by_time)
    provider = AnalyticEllipsoidVisibilityProvider()
    pairs = {}
    sites = data.get("ground_stations", {})
    elevation_rejected = range_rejected = 0
    for start, end in zip(times, times[1:]):
        common = sorted(by_time[start].keys() & by_time[end].keys())
        for left, right in combinations(common, 2):
            ranges, margins = [], []
            for fraction in (0, 0.25, 0.5, 0.75, 1):
                timestamp = start + fraction * (end - start)
                positions = []
                for node in (left, right):
                    a = by_time[start][node]["position_eci_m"]
                    b = by_time[end][node]["position_eci_m"]
                    positions.append(ground_state(sites[node], timestamp)[0] if node in sites else
                                     tuple(x + fraction * (y - x) for x, y in zip(a, b)))
                if any(node in sites and not above_mask(sites[node], timestamp, positions[1 - index])
                       for index, node in enumerate((left, right))):
                    elevation_rejected += 1
                    break
                distance = norm(sub(*positions))
                if distance > max_range_m:
                    range_rejected += 1
                    break
                visibility = provider.evaluate(VisibilityQuery(
                    source_id=left, destination_id=right,
                    source_position_eci_m=positions[0], destination_position_eci_m=positions[1]))
                if not visibility.geometrically_visible:
                    break
                ranges.append(distance)
                margins.append(visibility.limb_clearance_m)
            else:
                pairs.setdefault((left, right), []).append({
                    "source": left, "destination": right, "start_ms": start, "end_ms": end,
                    "range_m": max(ranges), "occultation_margin_m": min(margins),
                    "visibility": {"geometrically_visible": True, "earth_occulted": False,
                                   "reason": "VISIBLE", "fidelity": "ellipsoid:wgs84"},
                })
    windows = slice_contacts(pairs)
    return {"adapter": "gmat_comm_ephemeris.interval_contacts", "source": "GMAT",
            "geometry_model": "5-point piecewise-linear ECI interval visibility" +
                ("; GMST ground rotation and elevation mask" if sites else ""),
            "contacts": windows, "metrics": {**provider.metrics.as_dict(),
                "sampled_intervals": len(times) - 1, "window_count": len(windows),
                "ground_elevation_rejected": elevation_rejected, "max_range_rejected": range_rejected}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-range-m", type=float, default=12_000_000.0)
    args = parser.parse_args()
    output = convert(Path(args.input), Path(args.output), args.max_range_m)
    print("GMAT-COMM adapter: REAL GMAT JSON input")
    print(f"contacts generated: {len(output['contacts'])}")
    print(f"geometry tests: {output['metrics']['geometry_tests']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

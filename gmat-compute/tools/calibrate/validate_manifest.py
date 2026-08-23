#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path


def parse_simple_yaml(path: Path) -> dict[str, str]:
    stack: list[str] = []
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw.strip()
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        level = indent // 2
        stack = stack[:level]
        if value:
            values[".".join(stack + [key])] = value
        else:
            stack.append(key)
    return values


def check_csv(path: Path) -> list[str]:
    warnings: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        seen = set()
        for idx, row in enumerate(reader, start=2):
            if any(v is None or v == "" for v in row.values()):
                warnings.append(f"{path.name}:{idx}: missing value")
            key = tuple(row.items())
            if key in seen:
                warnings.append(f"{path.name}:{idx}: duplicate row")
            seen.add(key)
    return warnings


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_manifest.py measured/example_gpu/manifest.yaml")
        return 2
    manifest = Path(sys.argv[1])
    data = parse_simple_yaml(manifest)
    required = [
        "schema_version",
        "device.model",
        "provenance.source",
        "datasets.power_throughput.file",
        "units.temperature",
        "units.power",
        "extrapolation.policy",
    ]
    errors = [f"missing {key}" for key in required if key not in data]
    warnings: list[str] = []
    for key, value in data.items():
        if key.startswith("datasets.") and key.endswith(".file"):
            csv_path = manifest.parent / value
            if not csv_path.exists():
                errors.append(f"missing dataset {csv_path}")
            else:
                warnings.extend(check_csv(csv_path))
    if errors:
        print("Manifest validation: FAIL")
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Manifest validation: PASS")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
